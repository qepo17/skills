use e2e_skills_intro::{E2eSkillsIntroMedia, E2eSkillsIntroVideo};
use fframes::{
    AudioMixOptions, EncoderOptions, LimiterOptions, RenderOptions, StaticMediaProvider, cli,
};
use std::process::ExitCode;
fn main() -> ExitCode {
    let media = E2eSkillsIntroMedia::prepare().expect("embedded video assets");
    let video = E2eSkillsIntroVideo::default();
    cli::new(
        &video,
        RenderOptions {
            media: Some(&media),
            default_font: "DM Sans",
            audio_mix: AudioMixOptions {
                master_gain_db: 6.7,
                limiter: Some(LimiterOptions {
                    ceiling_db: -1.5,
                    ..Default::default()
                }),
                ..Default::default()
            },
            video_encoder_options: EncoderOptions {
                preferred_encoder: Some("libx264"),
                codec_params: Some(&[("crf", "20"), ("preset", "medium"), ("tune", "animation")]),
                ..Default::default()
            },
            ..Default::default()
        },
    )
    .run()
}
