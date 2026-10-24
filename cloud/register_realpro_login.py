"""Owner-run hidden prompts; create one new version of the existing Secret."""
from __future__ import annotations
import argparse
import getpass
import json
import subprocess


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',default='tatemono-map')
    parser.add_argument('--secret',default='tm-poc-realpro-login')
    args=parser.parse_args()
    print('新規ブラウザで実際にログインできる入口を選択してください。')
    print('1: realnetpro.com のRNPログイン')
    print('2: login.n-create.jp の店舗アカウント')
    print('3: login.n-create.jp の個人アカウント')
    route={'1':'rnp','2':'bb_store','3':'bb_personal'}.get(input('入口番号: ').strip())
    if not route:raise SystemExit('未登録: 入口番号が正しくありません。')
    username=getpass.getpass('ログインID（画面には表示しません）: ')
    password=getpass.getpass('パスワード（画面には表示しません）: ')
    repeat=getpass.getpass('パスワードをもう一度: ')
    if not username or not password or password!=repeat:
        raise SystemExit('未登録: 空欄またはパスワード不一致です。')
    payload=json.dumps({'username':username,'password':password,'login_route':route})
    result=subprocess.run(['gcloud','secrets','versions','add',args.secret,'--project',args.project,
        '--data-file=-','--format=value(name)'],input=payload,text=True,capture_output=True)
    if result.returncode:raise SystemExit('未登録: Secret Managerへの保存に失敗しました。')
    print('登録しました。入力内容は表示せず、既存バージョンも保持しています。')


if __name__=='__main__':main()
