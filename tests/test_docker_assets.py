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
        self.assertIn("web_jobs.py", dockerfile)
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

    def test_web_app_reads_password_from_environment_and_has_entrypoint(self):
        source = (ROOT / "web_app.py").read_text()
        self.assertIn("def main()", source)
        self.assertIn("VIDEOSYNC_PASSWORD", source)
        self.assertIn("main()", source)
        self.assertNotIn("if not expected:\n        return True", source)

    def test_web_app_exposes_upload_sync_preview_and_download(self):
        source = (ROOT / "web_app.py").read_text()
        self.assertIn("import web_jobs", source)
        self.assertIn("st.file_uploader", source)
        self.assertIn("SyncOptions", source)
        self.assertIn("run_sync_job", source)
        self.assertIn("st.video", source)
        self.assertIn("st.download_button", source)

    def test_readme_documents_docker_build_and_password(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("docker build -t videosync-web:dev .", readme)
        self.assertIn("VIDEOSYNC_PASSWORD", readme)
        self.assertIn("8501:8501", readme)


if __name__ == "__main__":
    unittest.main()
