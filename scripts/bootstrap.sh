#!/usr/bin/env bash
set -euo pipefail

BENCH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$BENCH_ROOT/configs/revisions.env"

mode="install"
if [[ $# -gt 1 ]]; then
  echo "usage: $0 [--verify-only]" >&2
  exit 2
fi
if [[ $# -eq 1 ]]; then
  if [[ "$1" != "--verify-only" ]]; then
    echo "usage: $0 [--verify-only]" >&2
    exit 2
  fi
  mode="verify"
fi

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "bootstrap currently supports Linux only" >&2
  exit 2
fi
case "$(uname -m)" in
  aarch64|arm64) node_arch="arm64" ;;
  x86_64|amd64) node_arch="x64" ;;
  *)
    echo "unsupported architecture: $(uname -m)" >&2
    exit 2
    ;;
esac

node_dist="node-v${NODE_VERSION}-linux-${node_arch}"
node_archive="${node_dist}.tar.xz"
node_dir="$BENCH_ROOT/$node_dist"
dsh_dir="$BENCH_ROOT/sources/deepseek-harness"
openclaw_dir="$BENCH_ROOT/sources/openclaw"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "required command is unavailable: $1" >&2
    exit 2
  fi
}

verify_checkout() {
  local label="$1"
  local directory="$2"
  local expected="$3"
  if [[ ! -d "$directory/.git" ]]; then
    echo "$label checkout is missing: $directory" >&2
    return 1
  fi
  local actual
  actual="$(git -C "$directory" rev-parse HEAD)"
  if [[ "$actual" != "$expected" ]]; then
    echo "$label revision mismatch: expected $expected, got $actual" >&2
    return 1
  fi
  echo "[verify] $label $actual"
}

verify_package_manager() {
  local label="$1"
  local directory="$2"
  local expected="$3"
  local declared
  declared="$(jq -r '.packageManager // ""' "$directory/package.json")"
  if [[ "$declared" != "pnpm@$expected" && "$declared" != "pnpm@$expected"+* ]]; then
    echo "$label packageManager mismatch: expected pnpm@$expected, got $declared" >&2
    return 1
  fi
  echo "[verify] $label package manager pnpm@$expected"
}

prepare_checkout() {
  local label="$1"
  local url="$2"
  local directory="$3"
  local commit="$4"
  if [[ ! -e "$directory" ]]; then
    echo "[clone] $label"
    git clone --filter=blob:none "$url" "$directory"
  elif [[ ! -d "$directory/.git" ]]; then
    echo "refusing to replace non-Git path: $directory" >&2
    exit 2
  fi
  if [[ -n "$(git -C "$directory" status --porcelain)" ]]; then
    echo "refusing to change dirty upstream checkout: $directory" >&2
    exit 2
  fi
  if ! git -C "$directory" cat-file -e "${commit}^{commit}" 2>/dev/null; then
    echo "[fetch] $label $commit"
    git -C "$directory" fetch --depth 1 origin "$commit"
  fi
  git -C "$directory" checkout --detach "$commit"
  verify_checkout "$label" "$directory" "$commit"
}

verify_node() {
  if [[ ! -x "$node_dir/bin/node" ]]; then
    echo "Node installation is missing: $node_dir" >&2
    return 1
  fi
  local actual
  actual="$($node_dir/bin/node --version)"
  if [[ "$actual" != "v$NODE_VERSION" ]]; then
    echo "Node version mismatch: expected v$NODE_VERSION, got $actual" >&2
    return 1
  fi
  echo "[verify] Node $actual ($node_arch)"
}

verify_builds() {
  [[ -f "$dsh_dir/apps/cli/lib/bin.js" ]] || {
    echo "DeepSeek Harness build output is missing" >&2
    return 1
  }
  [[ -f "$openclaw_dir/openclaw.mjs" && -d "$openclaw_dir/dist" ]] || {
    echo "OpenClaw build output is missing" >&2
    return 1
  }
  [[ -x "$BENCH_ROOT/.venv/bin/python" ]] || {
    echo "Python virtual environment is missing" >&2
    return 1
  }
  "$BENCH_ROOT/.venv/bin/python" -c \
    'from deepseek_harness import DeepSeekHarness; print("[verify] Python SDK import ok")'
}

require_command git
require_command jq
require_command rg
require_command sha256sum
require_command tar
require_command python3

if [[ "$mode" == "verify" ]]; then
  verify_checkout "DeepSeek Harness" "$dsh_dir" "$DSH_COMMIT"
  verify_checkout "OpenClaw" "$openclaw_dir" "$OPENCLAW_COMMIT"
  verify_package_manager "DeepSeek Harness" "$dsh_dir" "$DSH_PNPM_VERSION"
  verify_package_manager "OpenClaw" "$openclaw_dir" "$OPENCLAW_PNPM_VERSION"
  verify_node
  verify_builds
  echo "[done] bootstrap verification passed"
  exit 0
fi

require_command curl
mkdir -p "$BENCH_ROOT/sources" "$BENCH_ROOT/bin" "$BENCH_ROOT/.corepack" "$BENCH_ROOT/.pnpm-home"
prepare_checkout "DeepSeek Harness" "$DSH_REPO_URL" "$dsh_dir" "$DSH_COMMIT"
prepare_checkout "OpenClaw" "$OPENCLAW_REPO_URL" "$openclaw_dir" "$OPENCLAW_COMMIT"
verify_package_manager "DeepSeek Harness" "$dsh_dir" "$DSH_PNPM_VERSION"
verify_package_manager "OpenClaw" "$openclaw_dir" "$OPENCLAW_PNPM_VERSION"

if ! verify_node >/dev/null 2>&1; then
  archive_path="$BENCH_ROOT/$node_archive"
  if [[ ! -f "$archive_path" ]]; then
    echo "[download] Node v$NODE_VERSION ($node_arch)"
    temp_dir="$(mktemp -d)"
    trap 'rm -rf "$temp_dir"' EXIT
    curl --fail --location --retry 3 \
      "https://nodejs.org/dist/v${NODE_VERSION}/${node_archive}" \
      --output "$temp_dir/$node_archive"
    mv "$temp_dir/$node_archive" "$archive_path"
    rmdir "$temp_dir"
    trap - EXIT
  fi
  echo "[verify] $node_archive checksum"
  expected_line="$(rg "  ${node_archive}$" "$BENCH_ROOT/SHASUMS256.txt")"
  if [[ -z "$expected_line" ]]; then
    echo "checksum is not pinned for $node_archive" >&2
    exit 2
  fi
  printf '%s\n' "$expected_line" | (cd "$BENCH_ROOT" && sha256sum --check -)
  if [[ -e "$node_dir" ]]; then
    echo "refusing to replace incomplete Node directory: $node_dir" >&2
    exit 2
  fi
  tar -xJf "$archive_path" -C "$BENCH_ROOT"
fi
verify_node

export PATH="$BENCH_ROOT/bin:$node_dir/bin:${PATH:-/usr/bin:/bin}"
export COREPACK_HOME="$BENCH_ROOT/.corepack"
export PNPM_HOME="$BENCH_ROOT/.pnpm-home"
"$node_dir/bin/corepack" enable --install-directory "$BENCH_ROOT/bin"

echo "[install] DeepSeek Harness dependencies (pnpm $DSH_PNPM_VERSION)"
(cd "$dsh_dir" && corepack pnpm install --frozen-lockfile)
echo "[build] DeepSeek Harness"
(cd "$dsh_dir" && corepack pnpm run build)

echo "[install] OpenClaw dependencies (pnpm $OPENCLAW_PNPM_VERSION)"
(cd "$openclaw_dir" && corepack pnpm install --frozen-lockfile)
echo "[build] OpenClaw"
(cd "$openclaw_dir" && corepack pnpm run build)

if [[ ! -x "$BENCH_ROOT/.venv/bin/python" ]]; then
  echo "[create] Python virtual environment"
  python3 -m venv "$BENCH_ROOT/.venv"
fi
echo "[install] pinned Python dependencies"
"$BENCH_ROOT/.venv/bin/python" -m pip install \
  --requirement "$BENCH_ROOT/configs/python-bootstrap-requirements.txt"
"$BENCH_ROOT/.venv/bin/python" -m pip install --no-deps --editable "$dsh_dir/python/sdk"

verify_builds
echo "[done] bootstrap completed"
