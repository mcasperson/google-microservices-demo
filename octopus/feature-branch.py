import sys
import time
from functools import partial

from requests import get, post, delete, put
import argparse

from tenacity import retry, stop_after_delay, wait_fixed, retry_if_exception_type, stop_after_attempt


class OctopusApiError(Exception):
    pass


# Define shorthand decorator for the used settings.
retry_on_communication_error = partial(
    retry,
    stop=stop_after_delay(60) | stop_after_attempt(3),  # max. 60 seconds wait.
    wait=wait_fixed(0.4),  # wait 400ms
    retry=retry_if_exception_type(OctopusApiError),
)()


def parse_args():
    parser = argparse.ArgumentParser(description='Manage feature branches in Octopus.')
    parser.add_argument('--action', dest='action', action='store', help='create or delete',
                        required=True)
    parser.add_argument('--octopusUrl', dest='octopus_url', action='store', help='The Octopus server URL',
                        required=True)
    parser.add_argument('--octopusApiKey', dest='octopus_api_key', action='store', help='The Octopus API key',
                        required=True)
    parser.add_argument('--octopusSpace', dest='octopus_space', action='store', help='The Octopus space',
                        required=True)
    parser.add_argument('--octopusProject', dest='octopus_project', action='store',
                        help='A comma separated list of Octopus projects', required=True)
    parser.add_argument('--branchName', dest='branch_name', action='store', help='The Octopus environment',
                        required=True)
    parser.add_argument('--deploymentStepName', dest='deployment_step_name', action='store',
                        help='The name of the step that deploys the packages', required=True)
    parser.add_argument('--deploymentPackageName', dest='deployment_package_name', action='store',
                        help='The name of the package deployed in the step defined in deploymentStepName',
                        required=True)
    parser.add_argument('--targetName', dest='target_name', action='store',
                        help='The name of the target to assign to the new environment',
                        required=False)

    return parser.parse_args()


def build_headers():
    return {"X-Octopus-ApiKey": args.octopus_api_key}


def get_space_id(space_name):
    url = args.octopus_url + "/api/spaces?partialName=" + space_name.strip() + "&take=1000"
    response = get(url, headers=headers)
    spaces_json = response.json()

    filtered_items = [a for a in spaces_json["Items"] if a["Name"] == space_name.strip()]

    if len(filtered_items) == 0:
        sys.stderr.write("The space called " + space_name + " could not be found.\n")
        return None

    first_id = filtered_items[0]["Id"]
    return first_id


def get_resource_id(space_id, resource_type, resource_name):
    if space_id is None:
        return None

    url = args.octopus_url + "/api/" + space_id + "/" + resource_type + "?partialName=" \
          + resource_name.strip() + "&take=1000"
    response = get(url, headers=headers)
    json = response.json()

    filtered_items = [a for a in json["Items"] if a["Name"] == resource_name.strip()]
    if len(filtered_items) == 0:
        sys.stderr.write("The resource called " + resource_name + " of type " + resource_type
                         + " could not be found in space " + space_id + ".\n")
        return None

    first_id = filtered_items[0]["Id"]
    return first_id


def get_resource(space_id, resource_type, resource_id):
    if space_id is None:
        return None

    url = args.octopus_url + "/api/" + space_id + "/" + resource_type + "/" + resource_id
    response = get(url, headers=headers)
    json = response.json()

    return json


def create_environment(space_id, branch_name):
    environment_id = get_resource_id(space_id, "environments", branch_name)

    if environment_id is not None:
        sys.stderr.write("Found environment " + environment_id + "\n")
        return environment_id

    environment = {
        'Name': branch_name
    }
    url = args.octopus_url + "/api/" + space_id + "/environments"
    response = post(url, headers=headers, json=environment)
    if not response:
        raise OctopusApiError
    json = response.json()
    sys.stderr.write("Created environment " + json["Id"] + "\n")
    return json["Id"]


def create_lifecycle(space_id, environment_id, branch_name):
    lifecycle_id = get_resource_id(space_id, "lifecycles", branch_name)

    if lifecycle_id is not None:
        sys.stderr.write("Found lifecycle " + lifecycle_id + "\n")
        return lifecycle_id

    lifecycle = {
        'Id': None,
        'Name': branch_name,
        'SpaceId': space_id,
        'Phases': [{
            'Name': branch_name,
            'OptionalDeploymentTargets': [environment_id],
            'AutomaticDeploymentTargets': [],
            'MinimumEnvironmentsBeforePromotion': 0,
            'IsOptionalPhase': False
        }],
        'ReleaseRetentionPolicy': {
            'ShouldKeepForever': True,
            'QuantityToKeep': 0,
            'Unit': 'Days'
        },
        'TentacleRetentionPolicy': {
            'ShouldKeepForever': True,
            'QuantityToKeep': 0,
            'Unit': 'Days'
        },
        'Links': None
    }

    url = args.octopus_url + "/api/" + space_id + "/lifecycles"
    response = post(url, headers=headers, json=lifecycle)
    if not response:
        raise OctopusApiError
    json = response.json()
    sys.stderr.write("Created lifecycle " + json["Id"] + "\n")
    return json["Id"]


def find_channel(space_id, project_id, branch_name):
    if space_id is None:
        return None

    url = args.octopus_url + "/api/" + space_id + "/projects/" + project_id + "/channels?partialName=" \
          + branch_name.strip() + "&take=1000"
    response = get(url, headers=headers)
    json = response.json()

    filtered_items = [a for a in json["Items"] if a["Name"] == branch_name.strip()]
    if len(filtered_items) == 0:
        sys.stderr.write("The resource called " + branch_name + " of type channel could not be found in space "
                         + space_id + ".\n")
        return None

    first_id = filtered_items[0]["Id"]
    return first_id


def create_channel(space_id, project_id, lifecycle_id, step_name, package_name, branch_name):
    channel_id = find_channel(space_id, project_id, branch_name)

    if channel_id is not None:
        sys.stderr.write("Found channel " + channel_id + "\n")
        return channel_id

    # Create the channel json
    channel = {
        'ProjectId': step_name,
        'Name': branch_name,
        'SpaceId': space_id,
        'IsDefault': False,
        'LifecycleId': lifecycle_id,
        'Rules': [{
            'Tag': '^' + branch_name + '.*$',
            'Actions': [step_name],
            'ActionPackages': [{
                'DeploymentAction': step_name,
                'PackageReference': package_name
            }]
        }]
    }

    url = args.octopus_url + "/api/" + space_id + "/projects/" + project_id + "/channels"
    response = post(url, headers=headers, json=channel)
    if not response:
        raise OctopusApiError
    json = response.json()
    sys.stderr.write("Created channel " + json["Id"] + "\n")
    return json["Id"]


def assign_target(space_id, environment_id, target_name):
    if target_name is None or target_name.strip() == '':
        pass

    target_id = get_resource_id(space_id, "machines", target_name)
    if target_id is not None:
        url = args.octopus_url + "/api/" + space_id + "/machines/" + target_id
        get_response = get(url, headers=headers)

        if not get_response:
            raise OctopusApiError

        target = get_response.json()

        if target["EnvironmentIds"].index(environment_id) == -1:
            target["EnvironmentIds"].append(environment_id)
            put_response = put(url, headers=headers, json=target)

            if not put_response:
                raise OctopusApiError

            sys.stderr.write("Added environment " + environment_id + " to target " + target_id + "\n")
        else:
            sys.stderr.write("Environment " + environment_id + " already assigned to target " + target_id + "\n")


def cancel_tasks(space_id, project_id, branch_name):
    number_active_tasks = 0
    channel_id = find_channel(space_id, project_id, branch_name)
    if channel_id is not None:
        url = args.octopus_url + "/api/" + space_id + "/deployments?projects=" + project_id + "&channels=" + channel_id
        releases = get(url, headers=headers)
        json = releases.json()
        sys.stderr.write("Found " + str(len(json["Items"])) + " deployments\n")

        for deployment in json["Items"]:
            task_id = deployment["TaskId"]
            task_url = args.octopus_url + "/api/" + space_id + "/tasks/" + task_id
            task_response = get(task_url, headers=headers)
            task_json = task_response.json()

            if not task_json["IsCompleted"]:
                sys.stderr.write("Task " + task_id + " has not completed and will be cancelled\n")
                number_active_tasks += 1
                cancel_url = args.octopus_url + "/api/" + space_id + "/tasks/" + task_id + "/cancel"
                response = post(cancel_url, headers=headers)
                if not response:
                    raise OctopusApiError

    return number_active_tasks


def delete_releases(space_id, project_id, branch_name):
    channel_id = find_channel(space_id, project_id, branch_name)
    if channel_id is not None:
        url = args.octopus_url + "/api/" + space_id + "/projects/" + project_id + "/releases"
        releases = get(url, headers=headers)
        json = releases.json()
        channel_releases = [a for a in json["Items"] if a["ChannelId"] == channel_id]
        for release in channel_releases:
            url = args.octopus_url + "/api/" + space_id + "/releases/" + release["Id"]
            response = delete(url, headers=headers)
            if not response:
                raise OctopusApiError


def delete_channel(space_id, project_id, branch_name):
    channel_id = find_channel(space_id, project_id, branch_name)
    if channel_id is not None:
        url = args.octopus_url + "/api/" + space_id + "/projects/" + project_id + "/channels/" + channel_id
        response = delete(url, headers=headers)
        if not response:
            raise OctopusApiError
        sys.stderr.write("Deleted channel " + channel_id + "\n")


def delete_lifecycle(space_id, branch_name):
    lifecycle_id = get_resource_id(space_id, "lifecycles", branch_name)

    if lifecycle_id is not None:
        url = args.octopus_url + "/api/" + space_id + "/lifecycles/" + lifecycle_id
        response = delete(url, headers=headers)
        if not response:
            raise OctopusApiError
        sys.stderr.write("Deleted lifecycle " + lifecycle_id + "\n")


def delete_environment(space_id, branch_name):
    environment_id = get_resource_id(space_id, "environments", branch_name)

    if environment_id is not None:
        url = args.octopus_url + "/api/" + space_id + "/environments/" + environment_id
        response = delete(url, headers=headers)
        if not response:
            raise OctopusApiError
        sys.stderr.write("Deleted environment " + environment_id + "\n")


def unassign_target(space_id, branch_name, target_name):
    if target_name is None or target_name.strip() == '':
        return

    environment_id = get_resource_id(space_id, "environments", branch_name)

    if environment_id is None:
        return

    target_id = get_resource_id(space_id, "machines", target_name)
    if target_id is not None:
        url = args.octopus_url + "/api/" + space_id + "/machines/" + target_id
        get_response = get(url, headers=headers)

        if not get_response:
            raise OctopusApiError

        target = get_response.json()

        if target["EnvironmentIds"].index(environment_id) != -1:
            target["EnvironmentIds"] = [a for a in target["EnvironmentIds"] if a != environment_id]
            put_response = put(url, headers=headers, json=target)

            if not put_response:
                raise OctopusApiError

            sys.stderr.write("Removed environment " + environment_id + " from target " + target_id + "\n")
        else:
            sys.stderr.write("Environment " + environment_id + " not assigned to target " + target_id + "\n")

@retry_on_communication_error
def create_feature_branch():
    space_id = get_space_id(args.octopus_space)
    project_id = get_resource_id(space_id, "projects", args.octopus_project)
    environment_id = create_environment(space_id, args.branch_name)
    lifecycle_id = create_lifecycle(space_id, environment_id, args.branch_name)
    create_channel(space_id, project_id, lifecycle_id, args.deployment_step_name, args.deployment_package_name,
                   args.branch_name)
    assign_target(space_id, environment_id, args.target_name)


@retry_on_communication_error
def delete_feature_branch():
    space_id = get_space_id(args.octopus_space)
    project_id = get_resource_id(space_id, "projects", args.octopus_project)

    while True:
        tasks = cancel_tasks(space_id, project_id, args.branch_name)
        if tasks == 0:
            break
        time.sleep(10)

    delete_releases(space_id, project_id, args.branch_name)
    delete_channel(space_id, project_id, args.branch_name)
    delete_lifecycle(space_id, args.branch_name)
    unassign_target(space_id, args.branch_name, args.target_name)
    delete_environment(space_id, args.branch_name)


args = parse_args()
headers = build_headers()

if args.action == 'create':
    create_feature_branch()

if args.action == 'delete':
    delete_feature_branch()
