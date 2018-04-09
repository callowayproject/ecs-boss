import json
import click
from .ecs import EcsClient, EcrClient, CloudWatchLogClient
from .api import (validate as _validate, validate_task_def, build as _build,
                  docker_tag, run_command, create_or_update_task, get_latest_task_revision,
                  create_or_update_service, git_is_clean, git_tag)

AWS_KEY_HELP = 'AWS access key id. Default is derived from AWSACCESSKEYID environment variable.'
AWS_SECRET_HELP = 'AWS secret access key. Default is derived from AWSSECRETACCESSKEY environment variable.'
TAG_HELP = 'Tag for the image. This will skip the build step if an image with tag exists. Default is a datetime stamp.'
TASK_TAG_HELP = "If included, this task will use this tag for the image. Otherwise the image won't be changed."
REPOSITORY_HELP = 'The URI for the repository for the image. Default is derived from REPOSITORY environment variable'


@click.group()
def cli():
    """
    The root group for the sub commands
    """
    pass


def get_ecs_client(access_key_id=None, secret_access_key=None, region=None, profile=None):
    return EcsClient(access_key_id, secret_access_key, region, profile)


def get_ecr_client(access_key_id=None, secret_access_key=None, region=None, profile=None):
    return EcrClient(access_key_id, secret_access_key, region, profile)


def get_log_client(access_key_id=None, secret_access_key=None, region=None, profile=None):
    return CloudWatchLogClient(access_key_id, secret_access_key, region, profile)


@cli.command()
def check_git():
    """
    Makes sure that there aren't any uncommitted changes in git.
    """
    if not git_is_clean():
        raise click.ClickException("Please commit or stash your uncommitted changes.")


@cli.command()
@click.option('--task-file', type=click.File('r'), default="task-def.json")
@click.option('--access-key-id', required=False, help=AWS_KEY_HELP)
@click.option('--secret-access-key', required=False, help=AWS_SECRET_HELP)
def setup(task_file, access_key_id, secret_access_key):
    """
    Set up the Repository, load balancer and log group
    """
    import boto3
    from botocore.exceptions import ClientError

    try:
        local_task_file = json.loads(task_file.read())
    except (ValueError, ) as e:
        raise click.ClickException("Received an error reading the task file: {0}".format(e))

    validate_task_def(local_task_file)
    project_name = local_task_file['family']

    repository_name = project_name
    ecr_client = get_ecr_client(access_key_id, secret_access_key)
    repository = ecr_client.create_repository(repository_name)
    click.echo("")
    click.echo("Add this to your .env file")
    click.echo("")
    click.echo("REPOSITORY={0}".format(repository['repositoryUri']))
    click.echo("")
    click.echo("")

    log_group_name = "{0}-logs".format(project_name)
    log_client = get_log_client(access_key_id, secret_access_key)
    response = log_client.describe_log_groups(log_group_name)
    if response['ResponseMetadata']['HTTPStatusCode'] != 200:
        click.ClickException("Received an error getting log groups: {0}".format(response['ResponseMetadata']))
    if len(response['logGroups']) > 1:
        names = ", ".join([x['logGroupName'] for x in response['logGroups']])
        click.echo("There are multiple log groups with the same name: {0}".format(names))
        click.echo("I can't tell you which one to use.")
        click.echo("")
        click.echo("")
    else:
        if len(response['logGroups']) == 0:
            response = log_client.create_log_group(log_group_name)
            if response.get('error'):
                click.ClickException("Received an error creating log groups: {0}".format(response['error']))

        click.echo("")
        click.echo("Add this to your task definition for each container:")
        click.echo("")
        click.echo('"logConfiguration": {')
        click.echo('    "logDriver": "awslogs",')
        click.echo('    "options": {')
        click.echo('        "awslogs-group": "{0}",'.format(log_group_name))
        click.echo('        "awslogs-region": "us-east-1"')
        click.echo('    }')
        click.echo('},')
        click.echo("")
        click.echo("")

    load_balancer_name = project_name
    elb_client = boto3.client('elbv2')
    try:
        response = elb_client.describe_load_balancers(Names=[load_balancer_name])
        if len(response['LoadBalancers']) > 1:
            names = ", ".join([x['LoadBalancerName'] for x in response['LoadBalancers']])
            click.echo("There are multiple load balancers with the same name: {0}".format(names))
        else:
            lb = response['LoadBalancers'][0]
            click.echo("Add this to your service definition:")
            click.echo("")
            click.echo('"loadBalancers": [')
            click.echo('    {')
            click.echo('        "targetGroupArn": "{0}",'.format(lb['LoadBalancerArn']))
            click.echo('        "containerName": "{0}-container",'.format(project_name))
            click.echo('        "containerPort": 8000')
            click.echo('    }')
            click.echo('],')
            click.echo("")
            click.echo("Change containerName or containerPort if necessary.")
    except ClientError:
        click.echo("There is no load balancer named '{0}'. Please create one.".format(load_balancer_name))


@cli.command()
@click.option('--service-file', type=click.File('r'), default="service.json")
@click.option('--task-file', type=click.File('r'), default="task-def.json")
def validate(service_file, task_file):
    """
    Make sure the service file and task file are valid
    """
    _validate(task_file, service_file)
    click.echo("Everything looks good.")


@cli.command()
@click.option('--task-file', type=click.File('r'), default="task-def.json")
@click.option('--access-key-id', required=False, help=AWS_KEY_HELP)
@click.option('--secret-access-key', required=False, help=AWS_SECRET_HELP)
@click.option('--build-arg-str', required=False, default="", help="A string of build arguments to pass to docker.")
def build(task_file, access_key_id, secret_access_key, build_arg_str):
    """
    Build the docker image.
    """
    try:
        local_task_file = json.loads(task_file.read())
    except (ValueError, ) as e:
        raise click.ClickException("Received an error reading the task file: {0}".format(e))

    validate_task_def(local_task_file)
    project_name = local_task_file['family']
    _build(project_name, build_arg_str)


@cli.command()
@click.option('--access-key-id', required=False, help=AWS_KEY_HELP)
@click.option('--secret-access-key', required=False, help=AWS_SECRET_HELP)
@click.option('--image', required=True, help="The local Docker image to push to the remote repository")
@click.option('--repository', envvar='REPOSITORY', help=REPOSITORY_HELP)
@click.option('--tag', required=False, help=TAG_HELP)
def push_docker_image(access_key_id, secret_access_key, image, repository, tag):
    """
    Tag and push a docker image to a remote repository
    """
    ecr_client = get_ecr_client(access_key_id, secret_access_key)
    ecs_client = get_ecs_client(access_key_id, secret_access_key)
    docker_tag(ecs_client, ecr_client, image, repository, tag)


@cli.command()
@click.option('--service-file', type=click.File('r'), default="service.json")
@click.option('--task-file', type=click.File('r'), default="task-def.json")
@click.option('--access-key-id', required=False, help=AWS_KEY_HELP)
@click.option('--secret-access-key', required=False, help=AWS_SECRET_HELP)
@click.option('--repository', required=False, help="Deprecated. Ignored")
@click.option('--container-name', required=False, help="Name of the container to run the command. Defaults to the first container.")
@click.argument('command', nargs=-1)
def run_task_command(service_file, task_file, access_key_id, secret_access_key, repository, container_name, command):
    """
    Run a command using the latest task revision
    """
    import time

    local_task_file, local_service_file = _validate(task_file, service_file)
    ecs_client = get_ecs_client(access_key_id, secret_access_key)
    log_client = get_log_client(access_key_id, secret_access_key)

    cluster = local_service_file['cluster']
    task = get_latest_task_revision(ecs_client, local_task_file.family)
    log_config = None
    log_stream = None
    log_group = None

    if not container_name:
        container_name = task['containerDefinitions'][0]['name']
        log_config = task['containerDefinitions'][0]['logConfiguration']
    else:
        for cont in task['containerDefinitions']:
            if cont['name'] == container_name:
                log_config = cont['logConfiguration']
                break

    if len(command) == 1 and " " in command[0]:
        command = command[0].split(" ")
    overrides = {
        'containerOverrides': [{
            'name': container_name,
            'command': command,
        }],
    }
    click.echo("Running '{0}' in container '{1}' on task '{2}'.".format(" ".join(command), container_name, task.family_revision))
    result = ecs_client.run_task(cluster, task.family_revision, overrides=overrides)
    if result['failures']:
        click.ClickException("Error starting one-off task: {0}".format(result['failures']))

    task_id = result['tasks'][0]['taskArn'].split("/")[1]

    if log_config and log_config["logDriver"] == "awslogs":
        if "awslogs-stream-prefix" in log_config['options']:
            log_group = log_config['options']['awslogs-group']
            log_stream = "{0}/{1}/{2}".format(log_config['options']['awslogs-stream-prefix'], container_name, task_id)
            click.echo("Will retrieve logs from {0}".format(log_stream))

    cur_status = ''
    status = ''
    task_id = result['tasks'][0]['taskArn']
    next_token = None
    prev_next_token = None  # Apparently the next token can be reused if there is nothing more.

    while status != 'STOPPED':
        time.sleep(2)
        status = ecs_client.get_task_statuses(cluster, [task_id])[0]
        if status != cur_status:  # We only want to output the status when it changes
            cur_status = status
            click.echo("Task: {0} Command: {1} Status:{2}".format(task.family_revision, " ".join(command), status))
        if status == 'RUNNING' and log_stream is not None:
            kwargs = {
                'logGroupName': log_group,
                'logStreamName': log_stream,
            }
            if next_token is not None:
                kwargs['nextToken'] = next_token
            else:
                kwargs['startFromHead'] = True

            log_events = log_client.get_log_events(**kwargs)
            next_token = log_events['nextForwardToken']
            if next_token != prev_next_token:
                prev_next_token = next_token
                for event in log_events['events']:
                    click.echo(event['message'])

    while next_token:  # Get the rest of the logged events until there is no more tokens
        log_events = log_client.get_log_events(**kwargs)
        next_token = log_events['nextForwardToken']
        if next_token != prev_next_token:
            prev_next_token = next_token
            for event in log_events['events']:
                click.echo(event['message'])
        else:
            break
        time.sleep(2)

    click.echo("Done.")


@cli.command()
@click.option('--task-file', type=click.File('r'), default="task-def.json")
@click.option('--tag', required=False, help=TAG_HELP)
@click.option('--access-key-id', required=False, help=AWS_KEY_HELP)
@click.option('--secret-access-key', required=False, help=AWS_SECRET_HELP)
@click.option('--repository', envvar='REPOSITORY', help=REPOSITORY_HELP)
@click.option('--quiet', is_flag=True, help="Only return the resulting task family and revision")
def update_task(task_file, tag, access_key_id, secret_access_key, repository, quiet):
    """
    Update the remote task definition with the docker repo tag and any other
    modifications made to the local task definition
    """
    from .api import validate_task_def
    from .ecs import EcsTaskDefinition

    if not git_is_clean():
        raise click.ClickException("Please commit or stash your uncommitted changes.")

    if not repository:
        raise click.ClickException("Please set the REPOSITORY environment variable or pass the --respository flag.")

    try:
        local_task_file = EcsTaskDefinition(json.loads(task_file.read()))
        validate_task_def(local_task_file)
    except (ValueError, ) as e:
        raise click.ClickException("Received an error reading the task file: {0}".format(e))

    ecs_client = get_ecs_client(access_key_id, secret_access_key)
    ecr_client = get_ecr_client(access_key_id, secret_access_key)

    remote_tagged_img = ecr_client.has_tagged_image(repository, tag)
    if not remote_tagged_img:
        click.ClickException("There isn't a remote container with that tag. Please push a container with that tag first.")

    # Update the task def with the new tagged image
    task_definition = create_or_update_task(ecs_client, local_task_file, repository, tag)
    if quiet:
        click.echo(task_definition.revision)
    else:
        click.echo("Finished updating task: {0}".format(task_definition.family_revision))


@cli.command()
@click.option('--service-file', type=click.File('r'), default="service.json")
@click.option('--access-key-id', required=False, help=AWS_KEY_HELP)
@click.option('--secret-access-key', required=False, help=AWS_SECRET_HELP)
@click.argument('count', nargs=1)
def scale_service(service_file, access_key_id, secret_access_key, count):
    """
    Set the desired count of a service.
    """
    import time
    from api import validate_service_desc

    ecs_client = get_ecs_client(access_key_id, secret_access_key)

    try:
        local_service_file = json.loads(service_file.read())
        validate_service_desc(local_service_file)
    except (ValueError, ) as e:
        raise click.ClickException("Received an error reading the service file: {0}".format(e))

    family = local_service_file['taskDefinition'].split(":")[0]
    click.echo("Getting latest revision of {0}".format(family))
    task_def = ecs_client.describe_task_definition(family)
    if task_def is None:
        raise click.ClickException("Received an error reading the task: {0}".format(family))

    click.echo("Scaling service {0} to {1}.".format(local_service_file['serviceName'], count))
    ecs_client.update_service(
        local_service_file['cluster'],
        local_service_file['serviceName'],
        int(count),
        task_def.family_revision)

    # poll service every 10 seconds until count is reached or timeout is reached
    elapsed_time = 0
    while elapsed_time < 300:
        response = ecs_client.describe_services(local_service_file['cluster'], local_service_file['serviceName'])
        if response['services'][0]['runningCount'] == int(count):
            return
        time.sleep(10)
        elapsed_time += 10
    raise click.ClickException("The service {0} did not scale to {1} within the time allowed.".format(local_service_file['serviceName'], count))


@cli.command()
@click.option('--service-file', type=click.File('r'), default="service.json")
@click.option('--revision', required=False, help="The revision to use. Leave blank to use the latest revision.")
@click.option('--access-key-id', required=False, help=AWS_KEY_HELP)
@click.option('--secret-access-key', required=False, help=AWS_SECRET_HELP)
def update_service(service_file, revision, access_key_id, secret_access_key):
    """
    Update a service to a task revision.
    """
    from api import validate_service_desc

    ecs_client = get_ecs_client(access_key_id, secret_access_key)

    try:
        local_service_file = json.loads(service_file.read())
        validate_service_desc(local_service_file)
    except (ValueError, ) as e:
        raise click.ClickException("Received an error reading the task file: {0}".format(e))

    family = local_service_file['taskDefinition'].split(":")[0]
    if revision is None:
        click.echo("Getting latest revision of {0}".format(family))
        task_def = ecs_client.describe_task_definition(family)
        if task_def is None:
            raise click.ClickException("Received an error reading the task: {0}".format(family))
        task_revision = task_def.family_revision
    else:
        task_revision = "{0}:{1}".format(family, revision)

    click.echo("Updating service {0} to use task {1}.".format(local_service_file['serviceName'], task_revision))
    create_or_update_service(ecs_client, local_service_file, task_revision=task_revision)


@cli.command()
@click.option('--service-file', type=click.File('r'), default="service.json")
@click.option('--task-file', type=click.File('r'), default="task-def.json")
@click.option('--tag', required=False, help=TAG_HELP)
@click.option('--access-key-id', required=False, help=AWS_KEY_HELP)
@click.option('--secret-access-key', required=False, help=AWS_SECRET_HELP)
@click.option('--repository', envvar='REPOSITORY', help=REPOSITORY_HELP)
def update_task_and_service(service_file, task_file, tag, access_key_id, secret_access_key, repository):
    """
    Update the remote task and service definition with the docker repo tag and any other
    modifications made to the local task definition
    """
    if not git_is_clean():
        raise click.ClickException("Please commit or stash your uncommitted changes.")

    if not repository:
        raise click.ClickException("Please set the REPOSITORY environment variable or pass the --respository flag.")

    local_task_file, local_service_file = _validate(task_file, service_file)

    ecs_client = get_ecs_client(access_key_id, secret_access_key)
    ecr_client = get_ecr_client(access_key_id, secret_access_key)

    remote_tagged_img = ecr_client.has_tagged_image(repository, tag)
    if not remote_tagged_img:
        click.ClickException("There isn't a remote container with that tag. Please push a container with that tag first.")

    # Update the task def with the new tagged image
    task_definition = create_or_update_task(ecs_client, local_task_file, repository, tag)

    # Update the service def with the new task def
    create_or_update_service(ecs_client, local_service_file, task_definition)
    click.echo("Finished.")


@cli.command()
@click.option('--service-file', type=click.File('r'), default="service.json")
@click.option('--task-file', type=click.File('r'), default="task-def.json")
@click.option('--tag', required=False, help=TAG_HELP)
@click.option('--build-arg-str', required=False, default="", help="A string of build arguments to pass to docker.")
@click.option('--access-key-id', required=False, help=AWS_KEY_HELP)
@click.option('--secret-access-key', required=False, help=AWS_SECRET_HELP)
@click.option('--repository', envvar='REPOSITORY', help=REPOSITORY_HELP)
def deploy(service_file, task_file, tag, build_arg_str, access_key_id, secret_access_key, repository):
    """
    Build, tag, upload, update task, update service
    """
    import datetime

    if not git_is_clean():
        raise click.ClickException("Please commit or stash your uncommitted changes.")

    if not repository:
        raise click.ClickException("Please set the REPOSITORY environment variable or pass the --respository flag.")
    local_task_file, local_service_file = _validate(task_file, service_file)
    project_name = local_task_file['family']
    default_tag = datetime.datetime.utcnow().strftime("%Y-%m-%d-%H-%M-%S")
    tag = tag or default_tag

    # Tag the git repo
    current_branch = run_command("git rev-parse --abbrev-ref HEAD")
    git_tag(tag)
    _build(project_name, build_arg_str)
    run_command("git checkout {0}".format(current_branch))  # Since we may have detached HEAD from git_tag

    # tag the docker repo
    ecr_client = get_ecr_client(access_key_id, secret_access_key)
    ecs_client = get_ecs_client(access_key_id, secret_access_key)
    docker_tag(ecs_client, ecr_client, project_name, repository, tag)

    # Update the task def with the new tagged image
    task_definition = create_or_update_task(ecs_client, local_task_file, repository, tag)

    # Update the service def with the new task def
    create_or_update_service(ecs_client, local_service_file, task_definition)
    click.echo("Finished.")


@cli.command()
def version():
    """
    Print the version of the tool
    """
    from ecs_boss import __version__
    click.echo(__version__)


if __name__ == '__main__':
    cli()
