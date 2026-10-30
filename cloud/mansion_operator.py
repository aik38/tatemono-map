"""Owner-authorized MR deployment, preserving all pre-existing job settings.

stage: build three digest-pinned overlays; no Job changes.
apply: change only the images of the two existing Jobs, then configure the MR
weekly entry and its dedicated scheduler. Never launches Ulucks or RealPro.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

PROJECT='tatemono-map'
REGION='asia-northeast1'
REGISTRY=f'{REGION}-docker.pkg.dev/{PROJECT}/tatemono-poc'
BUCKET='tatemono-map-poc-523194690131'
RUNNER=f'tatemono-poc-runner@{PROJECT}.iam.gserviceaccount.com'
TRIGGER=f'tm-weekly-trigger@{PROJECT}.iam.gserviceaccount.com'


def command(*args):
    return subprocess.check_output(list(args),text=True)


def job(name):
    return json.loads(command('gcloud','run','jobs','describe',name,'--region='+REGION,'--format=json'))


def task(config):return config['spec']['template']['spec']['template']['spec']


def stable_spec(spec):
    result=copy.deepcopy(spec)
    metadata=result.get('template',{}).get('metadata',{})
    metadata.get('labels',{}).pop('client.knative.dev/nonce',None)
    metadata.get('annotations',{}).pop('run.googleapis.com/client-version',None)
    return result


def stage(root,work,sha):
    context=work/'build';context.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(root/'src/tatemono_map/building_registry/ingest_master_import.py',context/'ingest_master_import.py')
    for p in (root/'src/tatemono_map/cloud').glob('mansion_*.py'):shutil.copyfile(p,context/p.name)
    for name,src in [('fetch_public.py','cloud/fetch_public.py'),('effective_rentals.py','normalize/effective_rentals.py'),('building_summaries.py','normalize/building_summaries.py')]:
        shutil.copyfile(root/'src/tatemono_map'/src,context/name)
    shutil.copyfile(root/'cloud/Dockerfile.mansion-weekly',context/'Dockerfile')
    shutil.copyfile(root/'cloud/Dockerfile.mansion-shared',context/'Dockerfile.shared')
    configs={name:job(name) for name in ('tatemono-collection-poc','tatemono-realpro-weekly')}
    for name,config in configs.items():(work/(name+'.json')).write_text(json.dumps(config))
    images={'mansion':REGISTRY+'/mansion:full-'+sha[:12]}
    steps=[{'name':'gcr.io/cloud-builders/docker','args':['build','-t',images['mansion'],'.']}]
    for key,name in [('ulucks','tatemono-collection-poc'),('realpro','tatemono-realpro-weekly')]:
        base=task(configs[name])['containers'][0]['image']
        if '@sha256:' not in base:raise ValueError('production_base_image_not_digest_pinned')
        images[key]=REGISTRY+'/'+key+':mansion-shared-'+sha[:12]
        steps.append({'name':'gcr.io/cloud-builders/docker','args':['build','-f','Dockerfile.shared','--build-arg','BASE_IMAGE='+base,'-t',images[key],'.']})
    spec={'steps':steps,'images':list(images.values()),'timeout':'1800s'}
    (context/'cloudbuild.json').write_text(json.dumps(spec))
    response=json.loads(command('gcloud','builds','submit',str(context),'--config='+str(context/'cloudbuild.json'),'--async','--format=json','--quiet'))
    result={'build_id':response['id'],'images':images,'source_commit':sha}
    (work/'stage.json').write_text(json.dumps(result));print(json.dumps(result),flush=True)


def apply(work,sha):
    stage=json.loads((work/'stage.json').read_text())
    status=json.loads(command('gcloud','builds','describe',stage['build_id'],'--format=json'))
    if status['status']!='SUCCESS':raise ValueError('mansion_build_not_successful')
    images={item['name']:item['digest'] for item in status['results']['images']}
    pinned={key:tag.split(':')[0]+'@'+images[tag] for key,tag in stage['images'].items()}
    for key,name in [('ulucks','tatemono-collection-poc'),('realpro','tatemono-realpro-weekly')]:
        before=job(name)
        staged=json.loads((work/(name+'.json')).read_text())
        expected=copy.deepcopy(staged['spec']);expected['template']['spec']['template']['spec']['containers'][0]['image']=pinned[key]
        current=stable_spec(before['spec'])
        if current not in (stable_spec(staged['spec']),stable_spec(expected)):
            raise ValueError('existing_job_changed_since_staging')
        if current!=stable_spec(expected):
            command('gcloud','run','jobs','update',name,'--region='+REGION,'--image='+pinned[key],'--quiet')
        after=job(name)
        if stable_spec(after['spec'])!=stable_spec(expected):raise ValueError('existing_job_settings_not_preserved')
    command('gcloud','run','jobs','update','tatemono-mansion-weekly','--region='+REGION,'--image='+pinned['mansion'],
        '--command=python','--args=-m,tatemono_map.cloud.mansion_weekly,--weekly,--commit',
        '--task-timeout=86400s','--max-retries=1','--tasks=1','--parallelism=1',
        '--set-env-vars='+','.join(['TATEMONO_BUCKET='+BUCKET,'TATEMONO_SOURCE_COMMIT='+sha,'GOOGLE_CLOUD_PROJECT='+PROJECT,'TATEMONO_REGION='+REGION]),'--quiet')
    command('gcloud','run','jobs','add-iam-policy-binding','tatemono-mansion-weekly','--region='+REGION,'--member=serviceAccount:'+TRIGGER,'--role=roles/run.invoker','--quiet')
    scheduler='tatemono-mansion-weekly'
    describe=subprocess.run(['gcloud','scheduler','jobs','describe',scheduler,'--location='+REGION,'--format=json'],capture_output=True,text=True)
    action='update' if describe.returncode==0 else 'create'
    command('gcloud','scheduler','jobs',action,'http',scheduler,'--location='+REGION,'--schedule=10 14 * * 4','--time-zone=Asia/Tokyo',
        '--uri=https://run.googleapis.com/v2/projects/'+PROJECT+'/locations/'+REGION+'/jobs/tatemono-mansion-weekly:run',
        '--http-method=POST','--oauth-service-account-email='+TRIGGER,'--oauth-token-scope=https://www.googleapis.com/auth/cloud-platform',
        '--message-body={}','--attempt-deadline=180s','--quiet')
    result={'source_commit':sha,'images':pinned,'scheduler':json.loads(command('gcloud','scheduler','jobs','describe',scheduler,'--location='+REGION,'--format=json')),
        'existing_job_settings_preserved':True}
    (work/'applied.json').write_text(json.dumps(result));print(json.dumps({'status':'configured','source_commit':sha,'images':pinned,'scheduler':scheduler}),flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['stage','apply']);p.add_argument('--work',type=Path,default=Path('/tmp/mansion-deploy'));p.add_argument('--source-commit',required=True)
    args=p.parse_args();args.work.mkdir(parents=True,exist_ok=True)
    if args.mode=='stage':stage(Path(__file__).resolve().parents[1],args.work,args.source_commit)
    else:apply(args.work,args.source_commit)


if __name__=='__main__':main()
