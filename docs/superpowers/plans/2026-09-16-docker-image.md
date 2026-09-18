# VideoSync Docker Image Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible Docker image that runs the private Streamlit web MVP entrypoint for VideoSync.

**Architecture:** Keep the existing CLI engine as the rendering backend. Add a small Streamlit entrypoint and package the app with FFmpeg in a Python container. The first implementation slice proves the image builds and exposes the web process; upload/job orchestration can then grow behind the same entrypoint.

**Tech Stack:** Python 3.12, Streamlit, FFmpeg, Docker.

**Spec:** `docs/superpowers/specs/2026-09-16-web-mvp-design.md`

## Global Constraints

- Use Streamlit for the interface and the existing Python CLI as a subprocess.
- Deliver a reproducible Docker image, pinned application dependencies, a health endpoint, environment configuration instructions, and concise deployment steps.
- Read the password from deployment secrets, never repository source.
- Do not add a database, object storage, media library, GPU, or queue in v1.
- Preserve existing engine behavior and existing local edits.

---

### Task 1: Docker-Ready Web Entrypoint

**Files:**
- Create: `web_app.py`
- Create: `requirements-web.txt`
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `tests/test_docker_assets.py`

**Interfaces:**
- Produces: `web_app.py` with a `main() -> None` Streamlit entrypoint.
- Produces: Docker image command `streamlit run web_app.py --server.address=0.0.0.0 --server.port=8501`.
- Produces: `/healthz` endpoint through Streamlit's built-in health endpoint.

- [ ] **Step 1: Write failing tests for Docker assets**

```python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DockerAssetTests(unittest.TestCase):
    def test_dockerfile_installs_ffmpeg_and_runs_streamlit_app(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("python:3.12-slim", dockerfile)
        self.assertIn("ffmpeg", dockerfile)
        self.assertIn("requirements-web.txt", dockerfile)
        self.assertIn("streamlit", dockerfile)
        self.assertIn("web_app.py", dockerfile)
        self.assertIn("8501", dockerfile)

    def test_dockerignore_excludes_local_media_and_working_state(self):
        dockerignore = (ROOT / ".dockerignore").read_text()
        for pattern in [".git", ".venv", "__pycache__", "*.mp4", "*.mov", "rendered-*.mp4"]:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, dockerignore)

    def test_web_requirements_pin_streamlit_without_duplication(self):
        requirements = (ROOT / "requirements-web.txt").read_text().splitlines()
        self.assertIn("streamlit==1.63.0", requirements)
        self.assertIn("numpy==2.5.3", requirements)
        self.assertIn("imageio-ffmpeg==0.6.0", requirements)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m unittest tests.test_docker_assets -v`

Expected: FAIL because `tests/test_docker_assets.py` is not present before the step, then FAIL because Docker files are not present after the test file is added.

- [ ] **Step 3: Add minimal Docker implementation**

Create a Dockerfile that installs FFmpeg, installs pinned Python requirements, copies only application files, exposes port 8501, and runs Streamlit on all interfaces.

Create `.dockerignore` so local recordings, rendered MP4s, caches, virtual environments, and git state are excluded from the Docker build context.

Create `requirements-web.txt` containing the existing engine requirements and a pinned Streamlit version.

Create `web_app.py` with a minimal authenticated Streamlit shell that reads `VIDEOSYNC_PASSWORD` and presents the MVP entrypoint while upload orchestration is still being added.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m unittest tests.test_docker_assets -v`

Expected: PASS.

- [ ] **Step 5: Build the Docker image**

Run: `docker build -t videosync-web:dev .`

Expected: image builds successfully.

### Task 2: Container Usage Documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: Docker command from Task 1.
- Produces: concise local build/run instructions.

- [ ] **Step 1: Write failing documentation check**

Extend `tests/test_docker_assets.py`:

```python
def test_readme_documents_docker_build_and_password(self):
    readme = (ROOT / "README.md").read_text()
    self.assertIn("docker build -t videosync-web:dev .", readme)
    self.assertIn("VIDEOSYNC_PASSWORD", readme)
    self.assertIn("8501:8501", readme)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m unittest tests.test_docker_assets.DockerAssetTests.test_readme_documents_docker_build_and_password -v`

Expected: FAIL until README includes Docker instructions.

- [ ] **Step 3: Document local Docker usage**

Add a short README section with build and run commands:

```powershell
docker build -t videosync-web:dev .
docker run --rm -p 8501:8501 -e VIDEOSYNC_PASSWORD=change-me videosync-web:dev
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m unittest tests.test_docker_assets -v`

Expected: PASS.

### Self-Review

- Spec coverage: This first plan covers the Docker image, pinned web dependencies, Streamlit entrypoint, health behavior through Streamlit, secret-based password configuration, and deploy instructions. Upload/job orchestration remains covered by the web MVP spec but is outside this Docker-start slice.
- Placeholder scan: No `TBD`, `TODO`, or deferred implementation placeholders appear in plan steps.
- Type consistency: The only new Python interface is `web_app.main() -> None`, and Docker commands consistently reference `web_app.py` and port `8501`.
