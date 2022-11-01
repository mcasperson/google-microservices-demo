import sys
from requests import get, post, delete
import argparse


class OctopusApiError(Exception):
    pass


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
                        help='The name of the package deployed in the step defined in deploymentStepName', required=True)

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
        return environment_id

    environment = {
        'Name': branch_name
    }
    url = args.octopus_url + "/api/" + space_id + "/environments"
    response = post(url, headers=headers, json=environment)
    if not response:
        raise OctopusApiError
    json = response.json()
    return json["Id"]


def create_lifecycle(space_id, environment_id, branch_name):
    lifecycle_id = get_resource_id(space_id, "lifecycles", branch_name)

    if lifecycle_id is not None:
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
    lifecycle_id = find_channel(space_id, project_id, branch_name)

    if lifecycle_id is not None:
        return lifecycle_id

    # Create the channel json
    channel = {
        'ProjectId': step_name,
        'Name': branch_name,
        'SpaceId': space_id,
        'IsDefault': False,
        'LifecycleId': lifecycle_id,
        'Rules': [{
            'Tag': '.+',
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
    return json["Id"]


def cancel_tasks(space_id, project_id):
    None


def delete_releases(space_id, project_id):
    None


def delete_channel(space_id, project_id, branch_name):
    channel_id = find_channel(space_id, project_id, branch_name)
    if channel_id is not None:
        url = args.octopus_url + "/api/" + space_id + "/projects/" + project_id + "/channels/" + channel_id
        response = delete(url, headers=headers)
        if not response:
            raise OctopusApiError


def delete_lifecycle(space_id, branch_name):
    lifecycle_id = get_resource_id(space_id, "lifecycles", branch_name)

    if lifecycle_id is not None:
        url = args.octopus_url + "/api/" + space_id + "/lifecycles/" + lifecycle_id
        response = delete(url, headers=headers)
        if not response:
            raise OctopusApiError


def delete_environment(space_id, branch_name):
    environment_id = get_resource_id(space_id, "environments", branch_name)

    if environment_id is not None:
        url = args.octopus_url + "/api/" + space_id + "/environments/" + environment_id
        response = delete(url, headers=headers)
        if not response:
            raise OctopusApiError


def create_feature_branch():
    space_id = get_space_id(args.octopus_space)
    project_id = get_resource_id(space_id, "projects", args.octopus_project)
    environment_id = create_environment(space_id, args.branch_name)
    lifecycle_id = create_lifecycle(space_id, environment_id, args.branch_name)
    channel_id = create_channel(space_id, project_id, lifecycle_id, args.deployment_step_name, args.deployment_package_name, args.branch_name)


def delete_feature_branch():
    space_id = get_space_id(args.octopus_space)
    project_id = get_resource_id(space_id, "projects", args.octopus_project)
    cancel_tasks(space_id, project_id)
    delete_releases(space_id, project_id)
    delete_channel(space_id, project_id, args.branch_name)
    delete_lifecycle(space_id, args.branch_name)
    delete_environment(space_id, args.branch_name)


args = parse_args()
headers = build_headers()

if args.action == 'create':
    create_feature_branch()

if args.action == 'delete':
    delete_feature_branch()
