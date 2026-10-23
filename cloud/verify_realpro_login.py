"""Owner-only hidden comparison; never submits a login or alters the Secret."""
import getpass
import hmac
import json
import subprocess


def main():
    result = subprocess.run(
        ['gcloud', 'secrets', 'versions', 'access', '2',
         '--secret=tm-poc-realpro-login', '--project=tatemono-map'],
        capture_output=True, check=False)
    if result.returncode:
        print('Secretの照合準備に失敗しました。入力は不要です。')
        return 1
    saved = json.loads(result.stdout)
    del result
    print('手元の新規セッションでログインできた認証情報を照合します。')
    print('入力内容は表示・保存せず、ログイン送信やSecret変更も行いません。')
    entered_id = getpass.getpass('成功したログインID（非表示）: ')
    entered_password = getpass.getpass('成功したパスワード（非表示）: ')
    outcome = {
        'secret_version': '2',
        'username_matches': hmac.compare_digest(
            entered_id.encode(), saved['username'].encode()),
        'password_matches': hmac.compare_digest(
            entered_password.encode(), saved['password'].encode()),
    }
    del entered_id, entered_password, saved
    print('照合結果（認証情報は含みません）:')
    print(json.dumps(outcome, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
