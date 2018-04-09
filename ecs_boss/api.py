import json
import os
import time

import merge_structure
import click
from .ecs import EcsTaskDefinition
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True))

POLL_TIME = 2


def run_command(command, echo=False):
    """
    Simple wrapper to perform a command
    """
    from subprocess import Popen, PIPE, STDOUT
    p = Popen(command, shell=True, stdout=PIPE, stderr=STDOUT)
    if echo:
        for line in iter(p.stdout.readline, ''):
            click.echo(line.replace("\n", ""))
    else:
        return p.stdout.read()


def find_base_dir():
    """
    Find the directory that contains the Dockerfile. Look in the current working
    directory and move upward
    """
    docker_file = find_dotenv(filename='Dockerfile', raise_error_if_not_found=True, usecwd=True)
    return os.path.dirname(docker_file)


def validate_service_desc(service_desc):
    """
    Are the minimum keys in the service description?
    """
    required_keys = ['cluster', 'serviceName', 'taskDefinition', ]
    for key in required_keys:
        if key not in service_desc:
            raise click.ClickException("The service description file must include the key '{0}'.".format(key))
    if "loadBalancers" in service_desc and "role" not in service_desc:
        raise click.ClickException("The 'role' key must be included in the service description if you have a load balancer.")


def validate_task_def(task_def):
    """
    Are the minimum keys in the task definition?
    """
    required_keys = ['family', 'containerDefinitions']
    for key in required_keys:
        if key not in task_def:
            raise click.ClickException("The task definition file must include the key '{0}'.".format(key))

    for container in task_def['containerDefinitions']:
        for env_var in container.get("environment", []):
            if not isinstance(env_var["name"], basestring):
                raise click.ClickException("You have an environment variable name that is not a string: {0}".format(env_var["name"]))
            if not isinstance(env_var["value"], basestring):
                raise click.ClickException("You have an environment variable value for {0} that is not a string: {1}".format(env_var["name"], env_var["value"]))


def git_has_tag(tag):
    """
    Check if the git repo has the tag
    """
    result = run_command('git show-ref --tags {0}'.format(tag))
    if result:
        return True
    return False


def git_is_clean():
    """
    Make sure there aren't any uncommitted changes in git
    """
    # If this isn't a git repository, there isn't a problem.
    response = run_command('git -C . rev-parse')
    if 'Not a git repository' in response:
        return True

    # Update the index
    run_command('git update-index -q --ignore-submodules --refresh')

    clean = True

    # Disallow unstaged changes in the working tree
    response = run_command('git diff-files --name-status -r --ignore-submodules --')
    if response:
        click.echo("You have unstaged changes.")
        clean = False

    # Disallow uncommitted changes in the index
    response = run_command('git diff-index --cached --name-status -r --ignore-submodules HEAD --')
    if response:
        click.echo("Your index contains uncommitted changes.")
        clean = False

    return clean


def git_tag(tag):
    """
    Tag the git repository at the current commit or checkout a previous tagged commit.

    Warning: if it was a previous tagged commit, it will leave the repo in a
    detached state. You should run `git checkout master` afterwards to restore
    """
    if git_has_tag(tag):
        click.echo("Checking out existing tag '{0}' in git".format(tag))
        run_command("git checkout {0}".format(tag))
    else:
        click.echo("Tagging git repository with '{0}'".format(tag))
        run_command("git tag {0}".format(tag))
        run_command("git push --tags")


def docker_tag(ecs_client, ecr_client, project_name, repository, tag):
    """
    Tag the docker image, or use a previously tagged image
    """
    repository_host, repository_name = repository.split('/')

    # Make sure tag doesn't already exist remotely
    remote_tagged_img = tagged_img = False
    remote_tagged_img = ecr_client.has_tagged_image(repository_name, tag)
    if not remote_tagged_img:
        # Check to make sure the tag doesn't already exist locally
        docker_cmd = 'docker images --quiet {0}:{1}'.format(repository, tag)
        tagged_img = run_command(docker_cmd)
        if tagged_img:
            click.echo("Found previously locally tagged image")
    else:
        click.echo("Found tagged image in remote repository.")

    kwargs = {
        'project_name': project_name,
        'repository': repository,
        'tag': tag
    }
    if not tagged_img and not remote_tagged_img:
        click.echo("Tagging image with {0}".format(tag))
        docker_cmd = "docker tag {project_name} {repository}:{tag}".format(**kwargs)
        run_command(docker_cmd)

    if not remote_tagged_img:
        click.echo("Pushing to {repository}:{tag}".format(**kwargs))
        docker_cmd = "eval $(aws ecr get-login --no-include-email --region us-east-1) && " \
                    "docker push {repository}:{tag}".format(**kwargs)
        run_command(docker_cmd, echo=True)


def track_tasks(ecs_client, task_ids):
    """Poll task status until STOPPED"""
    while True:
        statuses = ecs_client.get_task_statuses(task_ids)
        if all([status == 'STOPPED' for status in statuses]):
            click.echo('ECS tasks {0} STOPPED'.format(','.join(task_ids)))
            break
        time.sleep(POLL_TIME)


def get_latest_task_revision(ecs_client, family_name):
    """
    Get the latest task revision of 'family_name'

    The ecs_client is passed in because the AWS keys are passed into the
    original function
    """
    results = ecs_client.boto.list_task_definition_families(familyPrefix=family_name)
    if family_name in results['families']:
        # The task definition exists
        return ecs_client.describe_task_definition(family_name)

    return None


def create_or_update_task(ecs_client, local_task_file, repository=None, tag=None):
    """
    Update or create the specified task

    The ecs_client is passed in because the AWS keys are passed into the
    original function
    """
    if tag and not repository:
        raise click.ClickException("Passed a tag without a repository.")

    family_name = local_task_file.family
    if tag:
        # Replace the 'image' value on container Definitions with the local value
        for cd in local_task_file['containerDefinitions']:
            cd['image'] = cd['image'].replace('%REPOSITORY%', repository)
            cd['image'] = cd['image'].replace('%RELEASE_TAG%', tag)
    else:
        # Remove the 'image' value on the container Definitions, use the
        # value already specified
        for cd in local_task_file['containerDefinitions']:
            del cd['image']

    task_def = get_latest_task_revision(ecs_client, family_name)
    if task_def is not None:
        click.echo("Merging remote task definition with local definition.")
        task_def = EcsTaskDefinition(merge_structure.recursive_update(task_def, local_task_file))
    else:
        click.echo("Remote task definition doesn't exist. Task will be created.")
        task_def = local_task_file
    click.echo("Registering task definition with ECS.")
    response = ecs_client.register_task_definition(
        task_def.family,
        task_def.containers,
        task_def.volumes,
        task_def.role_arn
    )
    if response['ResponseMetadata']['HTTPStatusCode'] == 200:
        new_task_def = EcsTaskDefinition(response['taskDefinition'])
        return new_task_def
    else:
        raise click.ClickException("Error received from AWS: {0}".format(response))


def create_or_update_service(ecs_client, service_desc, task_definition=None, task_revision=None):
    """
    Create or update an ECS service

    The ecs_client is passed in because the AWS keys are passed into the
    original function

    You must pass either a task_definition (an instance of EcsTaskDefinition) or
    a task_revision in the form "family:revision"
    """
    if task_definition is None and task_revision is None:
        raise click.ClickException("You must pass either a task definition or a task revision to create or update a service.")
    elif task_definition:
        family_revision = task_definition.family_revision
    elif task_revision:
        family_revision = task_revision

    cluster_name = service_desc['cluster']
    service_name = service_desc['serviceName']
    response = ecs_client.describe_services(cluster_name, service_name)

    current_service = {}
    for failure in response.get('failures', []):
        if failure['reason'] == 'MISSING':
            break
    if len(response['services']) == 1:
        current_service = response['services'][0]
    elif len(response['services']) > 1:
        service_names = [x['serviceName'] for x in response['services']]
        raise click.ClickException("Multiple services were returned: {0}".format(", ".join(service_names)))

    if not current_service:
        kwargs = {
            'cluster': cluster_name,
            'serviceName': service_name,
            'taskDefinition': family_revision,
            'desiredCount': service_desc.get('desiredCount', 1),
        }
        if 'loadBalancers' in service_desc:
            kwargs['loadBalancers'] = service_desc['loadBalancers']
        if 'clientToken' in service_desc:
            kwargs['clientToken'] = service_desc['clientToken']
        if 'role' in service_desc:
            kwargs['role'] = service_desc['role']
        if 'deploymentConfiguration' in service_desc:
            kwargs['deploymentConfiguration'] = service_desc['deploymentConfiguration']
        if 'placementConstraints' in service_desc:
            kwargs['placementConstraints'] = service_desc['placementConstraints']
        if 'placementStrategy' in service_desc:
            kwargs['placementStrategy'] = service_desc['placementStrategy']

        click.echo("Service '{0}' doesn't exist. You will have to create it manually.".format(service_name))
        # click.echo("Service '{0}' doesn't exist. Creating {0} on ECS.".format(service_name))
        # response = ecs_client.boto.create_service(**kwargs)
        # if response['ResponseMetadata']['HTTPStatusCode'] == 200:
        #     return response['service']
        # else:
        #     raise click.ClickException("Error received from AWS: {0}".format(response))
    else:
        # Merge the current service def with the local
        click.echo("Merging remote service definition with local definition.")
        new_service_def = merge_structure.recursive_update(current_service, service_desc)
        # push out the update
        kwargs = {
            'cluster': cluster_name,
            'service': service_name,
            'task_definition': family_revision,
            'desired_count': new_service_def.get('desiredCount', 1),
        }
        response = ecs_client.update_service(**kwargs)
        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            return response['service']
        else:
            raise click.ClickException("Error received from AWS: {0}".format(response))


def build(project_name, build_arg_str=""):
    """
    Do the actual building of the docker image.
    """
    # base_dir = find_base_dir()
    base_dir = "."
    click.echo("Building {0} from {1}".format(project_name, base_dir))
    docker_cmd = "docker build -t {0} {1} {2}".format(project_name, build_arg_str, base_dir)
    run_command(docker_cmd, echo=True)
    click.echo("Finished Building")


def validate(task_file, service_file):
    """
    Validate the task and service file is valid
    """
    try:
        local_task_file = EcsTaskDefinition(json.loads(task_file.read()))
        validate_task_def(local_task_file)
    except (ValueError, ) as e:
        raise click.ClickException("Received an error reading the task file: {0}".format(e))

    try:
        local_service_file = json.loads(service_file.read())
        validate_service_desc(local_service_file)
    except (ValueError, ) as e:
        raise click.ClickException("Received an error reading the service file: {0}".format(e))

    return local_task_file, local_service_file
