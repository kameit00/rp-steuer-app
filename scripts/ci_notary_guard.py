#!/usr/bin/env python3
"""Fail closed before CI credentials/builds when a Notary upload may exist.

This guard never deletes artifacts or resumes/submits Apple requests. Workflow
concurrency serializes runs; the two native architecture jobs may run together.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
STABLE_VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)')
REPOSITORY = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}')
RESUME_GUIDANCE = (
    'Do not rebuild or submit again. Recover the pending upload and submission '
    'ledger, then manually resume the same submission ID as described in docs/SIGNING.md. '
    'If the ID is unknown, reconcile Apple history first.'
)


class GuardError(Exception):
    """An intentionally credential-free diagnostic."""


def guard(arch):
    if arch not in ('arm64', 'x86_64'):
        raise GuardError('Unsupported architecture.')
    try:
        version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    except (OSError, UnicodeError):
        raise GuardError('Could not read the root VERSION file.') from None
    if not STABLE_VERSION.fullmatch(version):
        raise GuardError('VERSION must be a stable SemVer (MAJOR.MINOR.PATCH).')
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    if not REPOSITORY.fullmatch(repo):
        raise GuardError('Invalid GITHUB_REPOSITORY.')
    attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '')
    if not re.fullmatch(r'[1-9][0-9]*', attempt):
        raise GuardError('Invalid GITHUB_RUN_ATTEMPT.')
    env_file = Path(os.environ.get('GITHUB_ENV', ''))
    if not env_file.is_absolute() or not env_file.is_file():
        raise GuardError('Missing GitHub Actions environment file.')
    try:
        # Only validated, single-line release metadata reaches the workflow env.
        with env_file.open('a', encoding='utf-8') as stream:
            stream.write(f'APP_VERSION={version}\n')
    except OSError:
        raise GuardError('Could not record APP_VERSION in the workflow environment.') from None

    if attempt != '1':
        raise GuardError('Workflow re-runs cannot initiate notarization. ' + RESUME_GUIDANCE)
    if not os.environ.get('GH_TOKEN'):
        raise GuardError('Missing GitHub artifact-read token.')
    try:
        result = subprocess.run(
            ['gh', 'api', f'repos/{repo}/actions/artifacts', '--paginate',
             '--jq', '.artifacts[].name'],
            capture_output=True, text=True, check=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        # Never echo gh output, exceptions, environment, or authentication data.
        raise GuardError('Could not check previous pending artifacts; refusing notarization.') from None
    pending_name = f'pending-notarization-{version}-{arch}'
    # The API includes expired entries. They still block: expiration is not Apple
    # approval and must never silently permit another upload of the same release.
    if pending_name in result.stdout.splitlines():
        raise GuardError(f'A pending artifact exists for {version}/{arch}. ' + RESUME_GUIDANCE)
    print(f'CI notarization guard: No pending artifact for {version}/{arch}; first attempt allowed.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arch', required=True, choices=('arm64', 'x86_64'))
    args = parser.parse_args(argv)
    try:
        guard(args.arch)
    except GuardError as error:
        print(f'CI notarization guard: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
