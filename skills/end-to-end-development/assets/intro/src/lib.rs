//! A 34-second illustrated example of development across three repositories.
use fframes::{
    AudioMap, AudioTimestamp::*, AudioTrack, Color, Duration, FFramesContext, Frame, Scene, Scenes,
    Svgr, Transform, Video, animation::Easing, include_media_dir,
};

include_media_dir!(pub struct E2eSkillsIntroMedia, "media");
const INK: &str = "#202522";
const PAPER: &str = "#F6F4EA";
const MUTED: &str = "#606960";
const LIME: &str = "#D6F570";
const MINT: &str = "#AEE7D7";
const CORAL: &str = "#FFB29A";
const COLORS: [&str; 3] = [LIME, MINT, CORAL];
const REPOS: [&str; 3] = ["ui/", "backend/", "contract/"];
const LABELS: [&str; 6] = [
    "THE IDEA",
    "WORKSPACE ROOT",
    "PLAN + OWNERS",
    "IMPLEMENT",
    "VERIFY + WATCH",
    "THREE OPEN PRs",
];
// Cue times also drive the matching visual entrances and status changes.
const ROOT_PROMPT: f32 = 1.0;
const ROOT_START: f32 = 4.0;
const PLAN_START: f32 = 10.0;
const IMPLEMENT_START: f32 = 16.0;
const VERIFY_START: f32 = 22.0;
const FINALE_START: f32 = 27.0;
const TOTAL_SECONDS: f32 = 34.0;
const BUILD_STAGGER: f32 = 1.25;
const FIX_AT: f32 = 2.0;
const GREEN_AT: f32 = 3.0;
const PR_STAGGER: f32 = 0.12;

fn txt<'a>(x: f32, y: f32, size: usize, fill: &'a str, value: impl Into<String>) -> Svgr<'a> {
    let value = value.into();
    fframes::svgr!(<text x={x} y={y} font-family="DM Sans" font-weight="500" font-size={size} fill={fill}>{value}</text>)
}
fn center<'a>(x: f32, y: f32, size: usize, fill: &'a str, value: impl Into<String>) -> Svgr<'a> {
    let value = value.into();
    fframes::svgr!(<text x={x} y={y} text-anchor="middle" font-family="DM Sans" font-weight="500" font-size={size} fill={fill}>{value}</text>)
}
fn entrance(frame: &Frame, start: f32) -> (f32, f32) {
    let y = frame.animate_runtime(fframes::AnimateRuntimeInput {
        on_second: start,
        from: 65.0_f32,
        to: 0.0,
        animation_runtime: &fframes::animation::AnimationRuntime::new(
            2.0,
            &Easing::Spring {
                mass: 1.0,
                stiffness: 180.0,
                damping: 19.0,
            },
        ),
    });
    let opacity = ((frame.seconds() - start) / 0.25).clamp(0.0, 1.0);
    (y, opacity)
}
fn check<'a>(x: f32, y: f32, color: &'a str) -> Svgr<'a> {
    fframes::svgr!(<g transform={Transform::translate(x,y)}>
        <circle cx="0" cy="0" r="21" fill={color}/>
        <path d="M -9 0 L -2 7 L 11 -8" stroke={INK} stroke-width="4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
    </g>)
}
fn eyes<'a>(x: f32, y: f32, t: f32) -> Svgr<'a> {
    let dx = (t * 1.7).sin() * 3.;
    fframes::svgr!(<g>
        <ellipse cx={x} cy={y} rx="10" ry="14" fill={INK}/>
        <ellipse cx={x+34.} cy={y} rx="10" ry="14" fill={INK}/>
        <circle cx={x+dx+2.} cy={y-4.} r="3" fill="white"/>
        <circle cx={x+34.+dx+2.} cy={y-4.} r="3" fill="white"/>
    </g>)
}
fn header<'a>(title: &str, subtitle: &str) -> Svgr<'a> {
    fframes::svgr!(<g>{txt(170.,240.,96,INK,title)}{txt(174.,314.,40,MUTED,subtitle)}</g>)
}
fn repo_card<'a>(
    frame: &Frame,
    i: usize,
    y: f32,
    title: &str,
    detail: &str,
    status: &str,
    at: f32,
) -> Svgr<'a> {
    let (dy, opacity) = entrance(frame, at);
    let x = 170. + i as f32 * 555.;
    fframes::svgr!(<g opacity={opacity} transform={Transform::translate(x,y+dy)}>
        <rect x="6" y="8" width="470" height="340" rx="28" fill={INK}/>
        <rect width="470" height="340" rx="28" fill={COLORS[i]} stroke={INK} stroke-width="3"/>
        {txt(32.,66.,42,INK,title)}
        {eyes(382.,53.,frame.seconds()+i as f32)}
        <path d="M 32 101 H 438" stroke={INK} stroke-width="2" opacity="0.3"/>
        {txt(32.,178.,38,INK,detail)}
        {txt(32.,276.,30,INK,status)}
    </g>)
}

#[derive(Debug)]
pub struct Hook;
#[derive(Debug)]
pub struct Root;
#[derive(Debug)]
pub struct Coordinate;
#[derive(Debug)]
pub struct Implement;
#[derive(Debug)]
pub struct Verify;
#[derive(Debug)]
pub struct Finale;
macro_rules! scene {
    ($name:ident, $id:expr, $seconds:expr) => {
        impl Scene for $name {
            fn duration(&self) -> Duration<'_> {
                Duration::Seconds($seconds)
            }
            fn render_frame<'a>(&'a self, frame: Frame, _ctx: &FFramesContext<'a, '_>) -> Svgr<'a> {
                content($id, &frame)
            }
        }
    };
}
scene!(Hook, 0, 4.);
scene!(Root, 1, 6.);
scene!(Coordinate, 2, 6.);
scene!(Implement, 3, 6.);
scene!(Verify, 4, 5.);
scene!(Finale, 5, 7.);

fn content<'a>(scene: usize, frame: &Frame) -> Svgr<'a> {
    let t = frame.seconds();
    match scene {
        0 => {
            let cards: Vec<_> = (0..3)
                .map(|i| {
                    repo_card(
                        frame,
                        i,
                        452.,
                        REPOS[i],
                        ["The experience", "The logic", "The API schema"][i],
                        ["Click.", "Process.", "Define."][i],
                        0.22 + i as f32 * 0.12,
                    )
                })
                .collect();
            fframes::svgr!(<g>
                {header("One feature. Three repos.","Meet end-to-end-development.")}
                {cards}
                {center(960.,897.,42,INK,"Make them move together.")}
            </g>)
        }
        1 => {
            let prompt = "$end-to-end-development";
            let visible = ((t - ROOT_PROMPT).max(0.) * 28.) as usize;
            let typed: String = prompt.chars().take(visible).collect();
            let cursor = if t < 2.5 && ((t * 4.) as usize) % 2 == 0 {
                "|"
            } else {
                ""
            };
            let request_opacity = ((t - 2.0) / 0.35).clamp(0., 1.);
            fframes::svgr!(<g>
                {header("Start at the root.","Describe the feature you want.")}
                <rect x="170" y="390" width="495" height="446" rx="28" fill="#EBEDDF" stroke={INK} stroke-width="3"/>
                {txt(208.,457.,44,INK,"workspace/")}
                <path d="M 238 493 V 750 M 238 536 H 272 M 238 632 H 272 M 238 728 H 272" stroke="#87917E" stroke-width="3" fill="none"/>
                {txt(295.,550.,40,INK,"ui/")}{txt(295.,646.,40,INK,"backend/")}{txt(295.,742.,40,INK,"contract/")}
                <rect x="712" y="390" width="1038" height="446" rx="28" fill={INK}/>
                <circle cx="751" cy="429" r="8" fill={CORAL}/><circle cx="779" cy="429" r="8" fill={LIME}/><circle cx="807" cy="429" r="8" fill={MINT}/>
                {txt(845.,441.,28,"#BBC4B8","AI session / workspace root")}
                {txt(755.,530.,46,LIME,format!("{typed}{cursor}"))}
                <g opacity={request_opacity}>
                    {txt(755.,631.,48,PAPER,"Add order number")}
                    {txt(755.,696.,48,PAPER,"and pickup date filters.")}
                </g>
                {center(960.,906.,34,MUTED,"The agent discovers which repos need changes.")}
            </g>)
        }
        2 => {
            let tasks = [
                "Define filter parameters",
                "Implement filtered queries",
                "Build filter controls",
            ];
            let owners = ["contract/", "backend/", "ui/"];
            let rows: Vec<_> = (0..3).map(|i| {
                let at = 0.35 + i as f32 * 0.12;
                let (dy, opacity) = entrance(frame, at);
                let owner_opacity = ((t - at - 0.25) / 0.3).clamp(0., 1.);
                fframes::svgr!(<g opacity={opacity} transform={Transform::translate(170., 475. + i as f32 * 112. + dy)}>
                    {txt(34., 56., 32, "#BBC4B8", format!("0{}", i+1))}
                    {txt(117., 58., 42, PAPER, tasks[i])}
                    <g opacity={owner_opacity}>
                        <rect x="1140" y="10" width="398" height="74" rx="20" fill={COLORS[2-i]}/>
                        {txt(1172., 61., 38, INK, owners[i])}
                    </g>
                    <path d="M 34 99 H 1538" stroke="#495449" stroke-width="1"/>
                </g>)
            }).collect();
            fframes::svgr!(<g>
                {header("The plan assigns the owners.", "The agent inspects the workspace and maps the work.")}
                <rect x="170" y="380" width="1580" height="458" rx="28" fill={INK}/>
                {txt(204., 435., 30, LIME, "AI-GENERATED PLAN")}
                {txt(1310., 435., 30, "#BBC4B8", "OWNER")}
                {rows}
                {center(960., 916., 38, MUTED, "Focused workers follow the plan.")}
            </g>)
        }
        3 => {
            let names = ["contract/", "backend/", "ui/"];
            let details = ["OpenAPI parameters", "Filtered queries", "Filter controls"];
            let cards:Vec<_>=(0..3).map(|i|{
                let start=i as f32*BUILD_STAGGER+0.3;
                let (dy,o)=entrance(frame,start);
                let x=170.+555.*i as f32;
                let ready=t>start+0.85;
                let progress=((t-start)/0.85).clamp(0.001,1.);
                let state=if ready {"Implemented"} else {"Working..."};
                fframes::svgr!(<g opacity={o} transform={Transform::translate(x,430.+dy)}>
                    <rect width="470" height="370" rx="28" fill={COLORS[2-i]} stroke={INK} stroke-width="3"/>
                    {txt(32.,66.,42,INK,names[i])}
                    <rect x="28" y="108" width="414" height="124" rx="18" fill={INK}/>
                    {center(235.,183.,36,PAPER,details[i])}
                    <rect x="32" y="269" width="406" height="9" rx="4" fill="#FFFFFF" fill-opacity="0.6"/>
                    <rect x="32" y="269" width={406.*progress} height="9" rx="4" fill={INK}/>
                    {txt(32.,329.,32,INK,state)}
                    {if ready {check(412.,318.,PAPER)} else {Svgr::empty()}}
                </g>)
            }).collect();
            fframes::svgr!(<g>
                {header("Build in dependency order.","Shared contract first. Then matching backend and UI.")}
                <path d="M 654 601 H 707 M 690 588 L 707 601 L 690 614 M 1209 601 H 1262 M 1245 588 L 1262 601 L 1245 614" fill="none" stroke={INK} stroke-width="5" stroke-linecap="round"/>
                {cards}
                {center(960.,900.,38,INK,"One feature, connected end to end.")}
            </g>)
        }
        4 => {
            let green = t >= GREEN_AT;
            let fixing = t >= FIX_AT;
            let state = if green {
                "All checks green"
            } else if fixing {
                "Fix, push, re-check"
            } else {
                "One check needs a fix"
            };
            let status_color = if green { LIME } else { CORAL };
            fframes::svgr!(<g>
                {header("Test. Review. Fix. Repeat.","Verify locally, then watch every PR.")}
                <rect x="170" y="410" width="720" height="406" rx="28" fill="white" stroke={INK} stroke-width="3"/>
                {check(219.,483.,LIME)}{txt(260.,498.,42,INK,"Meaningful tests")}
                {check(219.,591.,LIME)}{txt(260.,606.,42,INK,"Independent review")}
                {check(219.,699.,LIME)}{txt(260.,714.,42,INK,"Cross-repo integration")}
                <rect x="935" y="410" width="815" height="406" rx="28" fill={INK}/>
                {txt(977.,482.,34,"#BBC4B8","PR WATCHER")}
                <rect x="977" y="530" width="731" height="109" rx="20" fill={status_color}/>
                {txt(1006.,599.,42,INK,state)}
                {txt(978.,735.,38,PAPER,if green {"Green + mergeable. Ready."} else {"Keep watching. Keep fixing."})}
                {center(960.,904.,36,MUTED,"Creating a PR starts the watch.")}
            </g>)
        }
        _ => {
            let cards:Vec<_>=(0..3).map(|i|{
                let (dy,o)=entrance(frame,0.25+i as f32*PR_STAGGER);
                let x=170.+555.*i as f32;
                fframes::svgr!(<g opacity={o} transform={Transform::translate(x,417.+dy)}>
                    <rect x="6" y="8" width="470" height="337" rx="28" fill={INK}/>
                    <rect width="470" height="337" rx="28" fill={COLORS[i]} stroke={INK} stroke-width="3"/>
                    {txt(32.,63.,42,INK,REPOS[i])}
                    <rect x="32" y="92" width="118" height="46" rx="23" fill={INK}/>
                    {txt(56.,125.,28,PAPER,"OPEN")}
                    {txt(32.,193.,34,INK,["Order filter controls", "Filtered order queries", "Order filter schema"][i])}
                    {check(52.,244.,PAPER)}{txt(87.,256.,30,INK,"Checks passed")}
                    {check(52.,294.,PAPER)}{txt(87.,306.,30,INK,"Mergeable")}
                    {eyes(379.,56.,t)}
                </g>)
            }).collect();
            let confetti:Vec<_>=(0..24).map(|i|{
                let x=200.+((i*139)%1520) as f32;
                let age=(t-0.6).max(0.);
                let y=345.+age*80.+((i*61)%240) as f32;
                let o=if t<0.6 {0.} else {(1.-age/2.0).clamp(0.,1.)};
                fframes::svgr!(<g opacity={o} transform={format!("translate({x} {y}) rotate({})",i as f32*23.+age*95.)}>
                    <rect width="12" height="23" rx="3" fill={COLORS[i%3]}/>
                </g>)
            }).collect();
            fframes::svgr!(<g>
                {header("One request. Three open PRs.","All connected. All ready for your review.")}
                {cards}{confetti}
                <rect x="459" y="829" width="1002" height="98" rx="49" fill={INK}/>
                {center(960.,893.,49,LIME,"$end-to-end-development")}
            </g>)
        }
    }
}

#[derive(Debug)]
pub struct E2eSkillsIntroVideo {
    hook: Hook,
    root: Root,
    coordinate: Coordinate,
    implement: Implement,
    verify: Verify,
    finale: Finale,
}
impl Default for E2eSkillsIntroVideo {
    fn default() -> Self {
        Self {
            hook: Hook,
            root: Root,
            coordinate: Coordinate,
            implement: Implement,
            verify: Verify,
            finale: Finale,
        }
    }
}
impl Video for E2eSkillsIntroVideo {
    const FPS: usize = 30;
    const WIDTH: usize = 1920;
    const HEIGHT: usize = 1080;
    const BACKGROUND_COLOR: Color = Color::hex("#F6F4EA");
    fn duration(&self) -> Duration<'_> {
        Duration::Auto
    }
    fn define_scenes(&self) -> Scenes<'_> {
        Scenes::from(vec![
            &self.hook as &dyn Scene,
            &self.root,
            &self.coordinate,
            &self.implement,
            &self.verify,
            &self.finale,
        ])
    }
    fn audio(&self) -> AudioMap<'_> {
        let mut tracks = vec![
            AudioTrack::new("music.wav", Second(0.)..Eof)
                .gain_db(-3.)
                .fade_in(0.15)
                .fade_out(1.2),
        ];
        for (at, file) in [
            (0.22, "pop.wav"),
            (0.34, "pop.wav"),
            (0.46, "pop.wav"),
            (ROOT_START - 0.1, "whoosh.wav"),
            (PLAN_START - 0.1, "whoosh.wav"),
            (IMPLEMENT_START - 0.1, "whoosh.wav"),
            (VERIFY_START - 0.1, "whoosh.wav"),
            (FINALE_START - 0.1, "whoosh.wav"),
            (PLAN_START + 0.35, "pop.wav"),
            (PLAN_START + 0.47, "pop.wav"),
            (PLAN_START + 0.59, "pop.wav"),
            (IMPLEMENT_START + 0.3, "pop.wav"),
            (IMPLEMENT_START + 0.3 + BUILD_STAGGER, "pop.wav"),
            (IMPLEMENT_START + 0.3 + BUILD_STAGGER * 2., "pop.wav"),
            (VERIFY_START + 0.35, "tick.wav"),
            (VERIFY_START + FIX_AT, "tick.wav"),
            (VERIFY_START + GREEN_AT, "success.wav"),
            (FINALE_START + 0.25, "pop.wav"),
            (FINALE_START + 0.25 + PR_STAGGER, "pop.wav"),
            (FINALE_START + 0.25 + PR_STAGGER * 2., "pop.wav"),
            (FINALE_START + 0.6, "success.wav"),
        ] {
            tracks.push(AudioTrack::new(file, Second(at)..Eof).gain_db(-5.));
        }
        for i in 0..22 {
            tracks.push(
                AudioTrack::new(
                    "tick.wav",
                    Second(ROOT_START + ROOT_PROMPT + i as f32 / 28.)..Eof,
                )
                .gain_db(-13.),
            );
        }
        AudioMap::from(tracks)
    }
    fn render_frame<'a>(&'a self, frame: Frame, ctx: &FFramesContext<'a, '_>) -> Svgr<'a> {
        let t = frame.seconds();
        let scene = if t < ROOT_START {
            0
        } else if t < PLAN_START {
            1
        } else if t < IMPLEMENT_START {
            2
        } else if t < VERIFY_START {
            3
        } else if t < FINALE_START {
            4
        } else {
            5
        };
        let dots:Vec<_>=(0..6).map(|i|fframes::svgr!(<circle cx={1570+i*30} cy="103" r="5" fill={if i<=scene {INK} else {"#D8DDCF"}}/>)).collect();
        fframes::svgr!(<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">
            <rect width="1920" height="1080" fill={PAPER}/>
            <path d="M 170 141 H 1750 M 170 969 H 1750" stroke="#D1D6C8" stroke-width="2"/>
            {txt(170.,114.,30,INK,"END-TO-END DEVELOPMENT")}
            {dots}
            {ctx.render_scenes(&frame)}
            {txt(170.,1022.,28,MUTED,format!("0{} / {}",scene+1,LABELS[scene]))}
            {txt(1360.,1022.,28,MUTED,"ONE CONNECTED FEATURE")}
            <rect x="170" y="967" width={(1580.*t/TOTAL_SECONDS).max(0.5)} height="4" rx="2" fill={INK}/>
        </svg>)
    }
}
