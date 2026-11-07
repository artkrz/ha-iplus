import argparse
import json
import sys
import time
from pathlib import Path
from .client import PlusClient, PlusError, read_credentials


def main():
    parser = argparse.ArgumentParser(description='Read Plus prepaid mobile internet balance')
    parser.add_argument('--credentials', default='.env')
    parser.add_argument('--session', default='session.json')
    parser.add_argument('--code-file', type=Path)
    parser.add_argument('--code-timeout', type=float, default=600)
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--login-only', action='store_true')
    args = parser.parse_args()
    def code_provider():
        print('SMS verification required.', file=sys.stderr, flush=True)
        if args.code_file:
            print(f'Waiting for SMS code in {args.code_file}', file=sys.stderr, flush=True)
            until = time.monotonic() + args.code_timeout
            while time.monotonic() < until:
                if args.code_file.exists():
                    value = args.code_file.read_text().strip()
                    if value:
                        return value
                time.sleep(1)
            raise PlusError('Timed out waiting for the SMS code')
        return input('SMS code: ').strip()
    client = None
    try:
        client = PlusClient(*read_credentials(args.credentials), session_path=args.session,
                            debug_dir='debug' if args.debug else None)
        client.ensure_session(code_provider)
        print(json.dumps({'authenticated': True} if args.login_only else client.get_balance(), ensure_ascii=False, indent=2))
        return 0
    except (PlusError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        if client:
            client.close()

if __name__ == '__main__':
    raise SystemExit(main())
