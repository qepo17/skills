# One request. Three open PRs.

A 34-second, 1920 × 1080, 30 fps fframes film. Generic repositories illustrate an order-filter feature spanning a UI, backend, and shared OpenAPI contract. This is an animated example, not a recording of live development or real PRs.

## Reproduce

Use Rust 1.93 or later and the platform build prerequisites for fframes 1.2.0, including libclang and the x264 development library. The project uses the CPU backend so it can also render on machines without a GPU. Cargo dependencies are pinned by `Cargo.lock`; the audio composer uses only Python's standard library.

Run these commands from this directory:

```sh
python3 generate_audio.py
cargo build --release --locked
cargo run --release --locked -- timeline
cargo run --release --locked -- inspect --all-frames --fail-on warning
cargo run --release --locked -- strip -n 24
cargo run --release --locked -- audio analyze
cargo run --release --locked -- render -o /tmp/end-to-end-development-render.mp4
```

To produce the compact README deliverables, export with FFmpeg:

```sh
ffmpeg -i /tmp/end-to-end-development-render.mp4 -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -c:a aac -b:a 192k -af volume=-0.5dB -movflags +faststart /tmp/end-to-end-development.mp4
ffmpeg -i /tmp/end-to-end-development.mp4 -vf 'fps=10,scale=720:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=96:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle' -loop 0 /tmp/end-to-end-development-preview.gif
```

The generated WAV files, build cache, and review images are ignored. Only the GIF in the parent assets directory is checked in for the READMEs. MP4 renders stay local and are ignored by Git.

Open the rendered MP4 in a video player to preview with sound, or run `ffplay /tmp/end-to-end-development-render.mp4`. This CPU build does not provide fframes' GPU preview window.

## Scenes

| Time | Story |
| --- | --- |
| 0–4 s | One feature, three expressive repo cards. |
| 4–10 s | Request order filters from the workspace root, without specifying repositories. |
| 10–16 s | The agent generates a plan mapping each task to its owning repository. |
| 16–22 s | Contract → backend → UI, in dependency order. |
| 22–27 s | Tests, review, integration, and a PR watcher fixing a failed check. |
| 27–34 s | Three open, green, mergeable PRs and the skill invocation. |

## Assets

`generate_audio.py` composes an original 120 BPM synth score and four original UI sound effects. Sound cues and matching visual event times are defined together in `src/lib.rs`. There are no third-party recordings or voice samples.

The bundled DM Sans Medium font is distributed under the SIL Open Font License in `FONT-LICENSE.txt`. The remaining artwork is SVG authored in the video source.
