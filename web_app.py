import hmac
import os
from pathlib import PureWindowsPath

import streamlit as st

import web_jobs


APP_TITLE = "VideoSync"
AUDIO_CHOICES = {
    "First video audio": "first",
    "Mix all videos": "mix",
    "Muted": "none",
}


def _password_is_configured():
    return bool(os.environ.get("VIDEOSYNC_PASSWORD"))


def _authenticated():
    return st.session_state.get("authenticated") is True


def _render_login():
    st.title(APP_TITLE)
    st.caption("Private beta")
    if not _password_is_configured():
        st.error("VIDEOSYNC_PASSWORD is not set.")
        return
    password = st.text_input("Password", type="password")
    if st.button("Continue"):
        expected = os.environ.get("VIDEOSYNC_PASSWORD", "")
        if hmac.compare_digest(password, expected):
            st.session_state.authenticated = True
            st.rerun()
        st.error("That password did not work.")


def _render_shell():
    web_jobs.cleanup_expired_jobs()
    st.title(APP_TITLE)
    st.caption("Private beta")
    st.info("Upload 2-4 MP4 or MOV clips with the same starting beep. Keep this page open while rendering; results expire after one hour.")

    layout_label = st.radio("Video layout", ["Side by side", "One below another"], horizontal=True)
    layout = "horizontal" if layout_label == "Side by side" else "vertical"
    order = "left-to-right" if layout == "horizontal" else "top-to-bottom"
    st.caption(f"Choose one clip per field. Video numbers set the {order} output order.")
    slots = [
        st.file_uploader(
            f"Video {index}" + (" (optional)" if index > 2 else ""),
            type=["mp4", "mov"],
            accept_multiple_files=False,
            max_upload_size=web_jobs.MAX_FILE_BYTES // (1024 * 1024),
            key=f"video_{index}",
        )
        for index in range(1, 5)
    ]
    uploads = [upload for upload in slots if upload is not None]
    if uploads:
        st.write("Output order:")
        for index, upload in enumerate(uploads, start=1):
            st.write(f"{index}. {upload.name}")

    audio_label = st.selectbox("Audio", list(AUDIO_CHOICES), index=1)
    frequency_mode = st.radio("Beep frequency", ["Auto detect", "Known Hz"], horizontal=True)
    frequency = "auto"
    if frequency_mode == "Known Hz":
        frequency = str(st.number_input("Frequency", min_value=1, max_value=20000, value=2700, step=1))

    ready = slots[0] is not None and slots[1] is not None
    if not ready:
        st.caption("Add Video 1 and Video 2 to start syncing.")
    if st.button("Sync videos", type="primary", disabled=not ready):
        _run_sync(uploads, AUDIO_CHOICES[audio_label], frequency, layout)

    _render_result()


def _run_sync(uploads, audio, frequency, layout="horizontal"):
    videos = [web_jobs.UploadedVideo(upload.name, upload.getvalue()) for upload in uploads]
    options = web_jobs.SyncOptions(audio=audio, frequency=frequency, layout=layout)
    try:
        with st.spinner("Analyzing beeps and rendering..."):
            result = web_jobs.run_sync_job(videos, options)
            result_bytes = result.output_path.read_bytes()
            result_filename = "vs_" + "_".join(PureWindowsPath(video.name).stem for video in videos) + ".mp4"
            st.session_state.job_result = result
            st.session_state.result_bytes = result_bytes
            st.session_state.result_filename = result_filename
        st.success("Sync complete.")
    except (RuntimeError, TimeoutError, ValueError, OSError) as exc:
        st.error(str(exc))


def _render_result():
    result_bytes = st.session_state.get("result_bytes")
    if not result_bytes:
        return

    st.subheader("Result")
    st.video(result_bytes, format="video/mp4")
    st.download_button(
        "Download MP4",
        data=result_bytes,
        file_name=st.session_state.get("result_filename", "videosync.mp4"),
        mime="video/mp4",
        on_click="ignore",
    )
    if st.button("Clear result"):
        web_jobs.clear_job(st.session_state.get("job_result"))
        st.session_state.pop("job_result", None)
        st.session_state.pop("result_bytes", None)
        st.session_state.pop("result_filename", None)
        st.rerun()


def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="video_camera", layout="centered")
    if not _authenticated():
        _render_login()
        return
    _render_shell()


if __name__ == "__main__":
    main()
