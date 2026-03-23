import io
import zipfile
import requests

from cifix import cache


GITHUB_API = "https://api.github.com"


def get_headers(token):
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def fetch_run_logs(repo, run_id, token, use_cache=True):
    """Download and extract workflow run logs from GitHub Actions.

    Args:
        repo: "owner/repo" string
        run_id: Workflow run ID
        token: GitHub personal access token
        use_cache: Check local cache before hitting the API (default True)

    Returns:
        List of (filename, content) tuples for each log file.

    Raises:
        RuntimeError: If the run is not found or logs are unavailable.
        ConnectionError: If unable to reach GitHub API.
    """
    if use_cache:
        cached = cache.get(repo, str(run_id))
        if cached is not None:
            return cached

    url = f"{GITHUB_API}/repos/{repo}/actions/runs/{run_id}/logs"

    try:
        resp = requests.get(url, headers=get_headers(token), allow_redirects=True, timeout=30)
    except requests.ConnectionError:
        raise ConnectionError(
            "Unable to reach GitHub API. Check your network connection."
        )
    except requests.Timeout:
        raise ConnectionError(
            "GitHub API request timed out. Try again later."
        )

    if resp.status_code == 404:
        raise RuntimeError(
            f"Run {run_id} not found in {repo}. "
            "Check the repo name and run ID, or ensure logs haven't expired."
        )
    if resp.status_code == 401:
        raise RuntimeError(
            "Authentication failed. Your GitHub token may be expired or invalid."
        )
    if resp.status_code == 403:
        raise RuntimeError(
            "Access denied. Your token may lack the 'actions:read' permission, "
            "or you may have hit a rate limit."
        )
    resp.raise_for_status()

    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            logs = []
            for name in sorted(zf.namelist()):
                if name.endswith(".txt"):
                    content = zf.read(name).decode("utf-8-sig", errors="replace")
                    logs.append((name, content))
    except zipfile.BadZipFile:
        raise RuntimeError(
            f"Received invalid log archive for run {run_id}. "
            "The run may still be in progress, or logs may have expired."
        )

    if use_cache:
        cache.put(repo, str(run_id), logs)

    return logs
