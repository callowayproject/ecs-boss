# Getting started

Info we need:

- AWS key: AWS_ACCESS_KEY
- AWS secret: AWS_SECRET_ACCESS_KEY
- Repository URI: REPOSITORY
- task definition name: retrieved from the task-def.json file
- service name: retrieved from the service.json file
- cluster name: retrieved from the service.json file
- task-def file
- service file

service file/task-def file placeholders

- %TASK_REV% : The latest revision of the task. Is updated to the new revision number if the task is updated.
- %RELEASE_TAG%: The release tag created by the deploy method.
- %REPOSITORY%: The repository for the container, e.g. `012345678910.dkr.ecr.us-east-1.amazonaws.com/my-project`


1. Create a `task-def.json` file
2. Create a `service.json` file


Commands:

- `build`: build the image without tagging or pushing to a repository. (convenience command)
- `deploy`: build image, tag image, push image to repository, update task, update service
- `update-task`: update the task and service without rebuilding a new image
- `update-service`: update the service without rebuilding the image or task

# task-def.json

This will manage your task definition and make versions of it for each deployment. It should be a valid JSON file.

Minimum requirements, example:

```json
{
  "family": "sleep360",
  "containerDefinitions": [
    {
      "name": "sleep",
      "image": "busybox:%RELEASE_TAG%",
      "cpu": 10,
      "memory": 10,
    }
  ]
}
```

**family:** The name for this task definition, which allows you to track multiple versions of the same task definition. Up to 255 letters (uppercase and lowercase), numbers, hyphens, and underscores are allowed.

**containerDefinitions:** A list of container definitions, although there is usually only one item. See [the container definition docs](http://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definition_parameters.html#container_definitions) for more information on all the attributes.

**containerDefinitions &rarr; name:** The name of the container. Up to 255 letters (uppercase and lowercase), numbers, hyphens, and underscores are allowed.

**containerDefinitions &rarr; image:** The image used to start a container. **IMPORTANT:** Use the placeholder `%RELEASE_TAG%` for the tag to have the tag filled in for you.

**containerDefinitions &rarr; memory:** The hard limit (in MiB) of memory to present to the container. If your container attempts to exceed the memory specified here, the container is killed.

You must specify a non-zero integer for one or both of `memory` or `memoryReservation` in container definitions.

**containerDefinitions &rarr; memoryReservation:** The soft limit (in MiB) of memory to reserve for the container. When system memory is under contention, Docker attempts to keep the container memory to this soft limit; however, your container can consume more memory when it needs to, up to either the hard limit specified with the memory parameter (if applicable), or all of the available memory on the container instance, whichever comes first.

**containerDefinitions &rarr; cpu:** The number of cpu units to reserve for the container. A container instance has 1,024 cpu units for every CPU core.

# service.json

This creates or updates the service. It should be a valid JSON file. This describes the bare minimum required to get a service to work. [View the full list.](http://docs.aws.amazon.com/AmazonECS/latest/developerguide/service_definition_paramters.html)

```json
{
    "cluster": "default",
    "serviceName": "sleepingBeauty",
    "taskDefinition": "sleep360:%TASK_REV%",
    "desiredCount": 1,
}
```

**cluster:** The short name or full Amazon Resource Name (ARN) of the cluster on which to run your service. If you do not specify a cluster, the default cluster is assumed.

**serviceName:** The name of your service. Up to 255 letters (uppercase and lowercase), numbers, hyphens, and underscores are allowed. Service names must be unique within a cluster.

**taskDefinition:** The family and revision (family:revision ) or full Amazon Resource Name (ARN) of the task definition to run in your service. You can use the `%TASK_REV%` placeholder to put the latest revision in automatically. If a revision is not specified, the latest ACTIVE revision is used.

**desiredCount:** The number of instantiations of the specified task definition to place and keep running on your cluster.

