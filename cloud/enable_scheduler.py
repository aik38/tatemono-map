"""Run only after production verification, using the dedicated deploy identity."""
import json
import os
import subprocess


def main():
    env = os.environ
    args = ['gcloud', 'scheduler', 'jobs']
    target = [env['GCP_SCHEDULER_JOB'], '--project', env['GCP_PROJECT_ID'], '--location', env['GCP_REGION']]
    result = subprocess.run(args + ['describe'] + target + ['--format=json(state,schedule,timeZone,httpTarget.uri)'], capture_output=True, text=True, check=True)
    job = json.loads(result.stdout)
    uri = f"https://run.googleapis.com/v2/projects/{env['GCP_PROJECT_ID']}/locations/{env['GCP_REGION']}/jobs/{env['GCP_JOB']}:run"
    if job.get('schedule') != '0 4 * * 1' or job.get('timeZone') != 'Asia/Tokyo' or job.get('httpTarget', {}).get('uri') != uri:
        raise RuntimeError('weekly_scheduler_contract_changed')
    if job.get('state') == 'PAUSED':
        subprocess.run(args + ['resume'] + target + ['--quiet'], check=True, capture_output=True)
    elif job.get('state') != 'ENABLED':
        raise RuntimeError('unexpected_scheduler_state')


if __name__ == '__main__':
    main()
