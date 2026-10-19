"""Keep native build failures visible in public GitHub check annotations."""
import os
import subprocess
import sys


def main():
    environment = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    result = subprocess.run(sys.argv[1:], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, env=environment)
    output = result.stdout.decode('utf-8', errors='replace')
    print(output, end='', flush=True)
    if result.returncode and os.environ.get('GITHUB_ACTIONS'):
        details = output[-24000:].replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
        print('::error title=Native Windows validation failed::' + details, flush=True)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
