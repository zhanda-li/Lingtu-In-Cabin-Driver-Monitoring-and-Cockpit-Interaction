"""Resolve target Linux markers against wheel METADATA without installing wheels.

Only HTTPS indexes/JSON/PEP658 metadata are fetched. Firmware, wheel bodies and
sdists are never fetched. This is a bounded metadata search, not a pip replacement
or an ELF/CPU/runtime compatibility test. Run pip check on the actual target too.
"""
import argparse
from datetime import datetime, timezone
from collections import defaultdict
from email.parser import BytesParser
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import time
from urllib.parse import unquote, urlsplit, urljoin
from urllib.request import Request, urlopen

from packaging.requirements import Requirement
from packaging.tags import cpython_tags, compatible_tags
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version, InvalidVersion
from packaging.specifiers import SpecifierSet

ROOT = Path(__file__).resolve().parents[1]


def target_environment(python):
    return dict(os_name='posix', sys_platform='linux', platform_machine='aarch64',
                platform_system='Linux', platform_release='', platform_version='',
                platform_python_implementation='CPython', implementation_name='cpython',
                implementation_version=python + '.0', python_version=python,
                python_full_version=python + '.0', extra='')


def target_tags(python, glibc):
    major, minor = map(int, python.split('.'))
    gmajor, gminor = map(int, glibc.split('.'))
    if gmajor != 2 or gminor < 17:
        raise ValueError('Only Linux glibc >=2.17 targets are supported')
    platforms = [f'manylinux_2_{v}_aarch64' for v in range(gminor, 16, -1)] + ['manylinux2014_aarch64']
    return set(cpython_tags((major, minor), [f'cp{major}{minor}'], platforms=platforms)) | set(
        compatible_tags((major, minor), interpreter=f'cp{major}{minor}', platforms=platforms))


def active(requirement, environment, extras=()):
    return requirement.marker is None or any(
        requirement.marker.evaluate(dict(environment, extra=extra)) for extra in ({''} | set(extras)))


def read_requirements(path):
    return [Requirement(line.split('#', 1)[0].strip()) for line in Path(path).read_text().splitlines()
            if line.split('#', 1)[0].strip()]


class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.append(dict(attrs))


class Index:
    def __init__(self, python, glibc, cache, offline=False):
        self.python = python; self.tags = target_tags(python, glibc)
        self.cache = Path(cache); self.cache.mkdir(parents=True, exist_ok=True)
        self.offline = offline; self.errors = []; self.memo = {}

    def get(self, url):
        # Cache only index/metadata, never wheel bodies. URL hash avoids filenames
        # from untrusted servers affecting local paths.
        if urlsplit(url).scheme != 'https' or urlsplit(url).path.endswith(('.whl', '.img', '.zip', '.gz')):
            raise ValueError('Only HTTPS metadata/index URLs are allowed')
        path = self.cache / (hashlib.sha256(url.encode()).hexdigest() + '.data')
        if path.exists():
            return path.read_bytes()
        if self.offline:
            raise RuntimeError(f'No cached metadata: {url}')
        for attempt in range(3):
            try:
                with urlopen(Request(url, headers={'User-Agent': 'Lingtu-arm64-metadata-audit/1'}), timeout=20) as response:
                    blob = response.read(24 * 1024 * 1024 + 1)
                if len(blob) > 24 * 1024 * 1024:
                    raise ValueError('Metadata exceeds size limit')
                path.write_bytes(blob)
                return blob
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(.3)

    def files(self, name, specifiers):
        if name == 'torch':
            url = 'https://download.pytorch.org/whl/cpu/torch/'
            parser = Links(); parser.feed(self.get(url).decode())
            result = []
            for attrs in parser.links:
                href = urljoin(url, attrs.get('href', ''))
                filename = unquote(urlsplit(href).path.rsplit('/', 1)[-1])
                result.append(dict(filename=filename, url=href.split('#')[0],
                                   hashes=dict(pair.split('=',1) for pair in urlsplit(href).fragment.split('&') if '=' in pair),
                                   metadata_hash=attrs.get('data-core-metadata') or attrs.get('data-dist-info-metadata')))
            return result
        data = json.loads(self.get(f'https://pypi.org/pypi/{name}/json'))
        versions = []
        for version in data['releases']:
            try:
                parsed = Version(version)
                if not parsed.is_prerelease and all(parsed in spec for spec in specifiers):
                    versions.append((parsed, version))
            except InvalidVersion:
                continue
        # Bounded backtracking; an exhausted search is a failure, never success.
        files = []
        for _, version in sorted(versions, reverse=True)[:12]:
            for entry in data['releases'][version]:
                if entry['packagetype'] == 'bdist_wheel' and not entry.get('yanked'):
                    files.append(entry)
        return files

    def candidates(self, name, requirements, constraints):
        specs = [r.specifier for r in requirements + constraints]
        seen = set()
        for entry in self.files(name, specs):
            try:
                wheel_name, version, _, tags = parse_wheel_filename(entry['filename'])
            except Exception:
                continue
            if (canonicalize_name(wheel_name) != name or version in seen or
                    not all(version in s for s in specs) or not tags.intersection(self.tags)):
                continue
            python_spec = entry.get('requires_python')
            if python_spec and Version(self.python + '.0') not in SpecifierSet(python_spec):
                continue
            url = entry['url'].split('#')[0] + '.metadata'
            try:
                blob = self.get(url)
                expected = entry.get('metadata_hash')
                digest = hashlib.sha256(blob).hexdigest()
                if expected and expected != 'true' and expected != 'sha256=' + digest:
                    raise ValueError('PEP658 metadata SHA256 mismatch')
                metadata = BytesParser().parsebytes(blob)
                if (canonicalize_name(metadata['Name']) != name or Version(metadata['Version']) != version):
                    raise ValueError('Wheel metadata identity mismatch')
                if metadata['Requires-Python'] and Version(self.python + '.0') not in SpecifierSet(metadata['Requires-Python']):
                    continue
                dependencies = metadata.get_all('Requires-Dist', [])
                record = dict(name=name, version=str(version), filename=entry['filename'],
                                   url=entry['url'].split('#')[0], wheel_sha256=(entry.get('hashes') or entry.get('digests', {})).get('sha256'),
                                   metadata_url=url, metadata_sha256=digest,
                                   metadata_hash_verified=bool(expected and expected.startswith('sha256=')),
                                   requires_python=metadata['Requires-Python'], requires_dist=dependencies,
                                   matching_tags=sorted(map(str, tags.intersection(self.tags))))
                seen.add(version)
                yield record
            except Exception as exc:
                self.errors.append(dict(package=name, url=url, error=f'{type(exc).__name__}: {exc}'))


def resolve(index, roots, constraints, environment, limit=600):
    iterations = 0; failures = []

    def walk(selected):
        nonlocal iterations
        iterations += 1
        if iterations > limit:
            raise RuntimeError('Metadata search bound exceeded; no installability claim')
        required = defaultdict(dict)
        def add(req):
            required[canonicalize_name(req.name)][str(req)] = req
        for root in roots:
            if active(root, environment): add(root)
        # Re-expand when a later dependency adds an extra to a selected package.
        while True:
            previous = sum(map(len, required.values()))
            for name, record in selected.items():
                if name not in required: continue
                extras = set().union(*(r.extras for r in required[name].values()))
                for text in record['requires_dist']:
                    req = Requirement(text)
                    if active(req, environment, extras): add(req)
            if sum(map(len, required.values())) == previous: break
        for name, record in selected.items():
            if name in required and not all(Version(record['version']) in r.specifier
                                            for r in list(required[name].values()) + constraints.get(name, [])):
                return None
        missing = [name for name in required if name not in selected]
        if not missing:
            return {name: dict(record, active_requirements=sorted(required[name]))
                    for name, record in selected.items() if name in required}
        # Resolve constrained core packages before freely moving dependencies.
        name = sorted(missing, key=lambda n: (n not in constraints, n))[0]
        candidates = index.candidates(name, list(required[name].values()), constraints.get(name, []))
        found = False
        for record in candidates:
            found = True
            answer = walk(dict(selected, **{name: record}))
            if answer is not None: return answer
        if not found:
            failures.append(dict(package=name, requirements=sorted(required[name]),
                                 constraints=[str(r) for r in constraints.get(name, [])]))
        return None

    result = walk({})
    return result, failures, iterations


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--python', choices=['3.11', '3.12'], required=True)
    ap.add_argument('--glibc', required=True)
    ap.add_argument('--cache', type=Path, default=ROOT / 'runs/arm64_metadata_cache')
    ap.add_argument('--offline', action='store_true')
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    env = target_environment(args.python)
    constraints = defaultdict(list)
    for req in read_requirements(ROOT / 'constraints-arm64.txt'):
        if active(req, env): constraints[canonicalize_name(req.name)].append(req)
    index = Index(args.python, args.glibc, args.cache, args.offline)
    selected = None; failures = []; iterations = 0; error = None
    try:
        selected, failures, iterations = resolve(index, read_requirements(ROOT / 'requirements-arm64.txt'), constraints, env)
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    forbidden = [name for name in (selected or {}) if name.startswith(('nvidia-', 'cuda-')) or name == 'triton']
    success = selected is not None and not forbidden
    report = dict(schema=1, generated_at_utc=datetime.now(timezone.utc).isoformat(),
                  input_sha256={name: hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
                                for name in ('requirements-arm64.txt','constraints-arm64.txt','tools/resolve_arm64_metadata.py')},
                  python=args.python, glibc=args.glibc, target_environment=env,
                  metadata_resolution_passed=success, board_validation='待板端验证',
                  installed=False, wheel_bodies_downloaded=False, search_iterations=iterations,
                  selected=selected or {}, missing_or_conflicts=failures, metadata_errors=index.errors,
                  forbidden_cpu_dependencies=forbidden, error=error,
                  limits=['Bounded candidate search (12 stable versions/package)',
                          'No ELF/shared-library/CPU instruction or runtime verification',
                          'PyPI metadata recorded over HTTPS; CPU index metadata hash checked when supplied',
                          'Exact target patch Python/kernel/BSP still unknown'])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(passed=success, packages=len(report['selected']), output=str(args.out), error=error)))
    raise SystemExit(0 if success else 1)


if __name__ == '__main__':
    main()
