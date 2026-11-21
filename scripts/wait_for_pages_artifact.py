"""Wait briefly for a newly uploaded Pages artifact to become discoverable."""
import argparse
import json
import os
import re
import subprocess
import time


MAX_ATTEMPTS = 7
POLL_SECONDS = 5
REQUEST_TIMEOUT = 10
ARTIFACT_NAME = 'github-pages'


class ArtifactWaitError(Exception):
    pass


def validate_target(repo, run_id):
    if (not isinstance(repo, str)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', repo)
            or not isinstance(run_id, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', run_id)):
        raise ArtifactWaitError('Invalid repository or workflow run; no artifact check was made.')


def ready_artifact(payload):
    """Reject incomplete/ambiguous responses rather than choosing an artifact."""
    if (not isinstance(payload, dict) or type(payload.get('total_count')) is not int
            or not isinstance(payload.get('artifacts'), list)
            or payload['total_count'] != len(payload['artifacts'])
            or len(payload['artifacts']) > 100):
        raise ArtifactWaitError('Artifact metadata is incomplete or malformed; readiness is not confirmed.')
    matches = []
    for row in payload['artifacts']:
        if not isinstance(row, dict) or not isinstance(row.get('name'), str):
            raise ArtifactWaitError('Artifact metadata is malformed; readiness is not confirmed.')
        if row['name'] != ARTIFACT_NAME:
            continue
        if type(row.get('expired')) is not bool:
            raise ArtifactWaitError('Artifact expiry is unconfirmed; readiness is not confirmed.')
        if not row['expired']:
            matches.append(row)
    if len(matches) > 1:
        raise ArtifactWaitError('Multiple active Pages artifacts were found; publication must stop.')
    if not matches:
        return None
    row = matches[0]
    if (type(row.get('id')) is not int or row['id'] <= 0
            or type(row.get('size_in_bytes')) is not int or row['size_in_bytes'] <= 0):
        raise ArtifactWaitError('Pages artifact identity or size is invalid; readiness is not confirmed.')
    return row['id']


def wait_for_pages_artifact(repo, run_id, *, runner=None, sleeper=None):
    validate_target(repo, run_id)
    runner = subprocess.run if runner is None else runner
    sleeper = time.sleep if sleeper is None else sleeper
    endpoint = 'repos/' + repo + '/actions/runs/' + run_id + '/artifacts?name=' + ARTIFACT_NAME + '&per_page=100'
    args = ['gh', 'api', '--hostname', 'github.com', '--method', 'GET', endpoint]
    for attempt in range(MAX_ATTEMPTS):
        payload = None
        received = False
        try:
            result = runner(args, text=True, capture_output=True, timeout=REQUEST_TIMEOUT, check=False)
            if result.returncode == 0:
                # JSON corruption is distinct from temporary network failure.
                # Do not print GH output: it may contain headers or credentials.
                try:
                    payload = json.loads(result.stdout)
                    received = True
                except (TypeError, ValueError):
                    raise ArtifactWaitError('GitHub returned malformed artifact metadata; publication must stop.') from None
        except (OSError, subprocess.SubprocessError):
            pass  # An unavailable metadata endpoint may recover on the next poll.
        if received:
            artifact_id = ready_artifact(payload)
            if artifact_id is not None:
                return artifact_id
        if attempt < MAX_ATTEMPTS - 1:
            sleeper(POLL_SECONDS)
    raise ArtifactWaitError('Pages artifact was not discoverable after seven checks; publication must stop.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY'))
    parser.add_argument('--run-id', default=os.environ.get('GITHUB_RUN_ID'))
    args = parser.parse_args(argv)
    try:
        artifact_id = wait_for_pages_artifact(args.repo, args.run_id)
        print('Pages artifact is discoverable: ' + str(artifact_id) + '.')
        return 0
    except ArtifactWaitError as error:
        print(str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
