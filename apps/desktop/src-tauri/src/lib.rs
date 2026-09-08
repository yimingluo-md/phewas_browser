//! PheWAS Browser desktop shell.
//!
//! The whole UI and all data logic live in the `phewas-server` sidecar (a frozen Python
//! process). This shell only: generates a per-launch token, starts the sidecar, waits for it
//! to print its URL, points the WebView at it, provides native menus/dialogs, keeps a single
//! instance, and kills the sidecar on quit. Nothing here knows about genes or variants.

use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Duration;

use rand::{distributions::Alphanumeric, Rng};
use tauri::menu::{AboutMetadataBuilder, MenuBuilder, MenuItemBuilder, PredefinedMenuItem, SubmenuBuilder};
use tauri::{AppHandle, Manager, RunEvent, WebviewWindow, WindowEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const SIDECAR_NAME: &str = "phewas-server";
const STARTUP_TIMEOUT: Duration = Duration::from_secs(60);

struct Sidecar(Mutex<Option<CommandChild>>);

fn token() -> String {
    rand::thread_rng().sample_iter(&Alphanumeric).take(40).map(char::from).collect()
}

/// Where the sidecar executable is, in order of preference:
/// 1. `PHEWAS_SIDECAR` (developer override, a path to the executable)
/// 2. bundled: `<resources>/sidecar/phewas-server/phewas-server[.exe]`
/// 3. development checkout: `uv run phewas-server` from the repository root
enum Launch {
    Exe(PathBuf),
    Uv(PathBuf),
}

fn resolve_sidecar(app: &AppHandle) -> Result<Launch, String> {
    if let Ok(p) = std::env::var("PHEWAS_SIDECAR") {
        return Ok(Launch::Exe(PathBuf::from(p)));
    }
    let exe = if cfg!(windows) { format!("{SIDECAR_NAME}.exe") } else { SIDECAR_NAME.to_string() };
    if let Ok(res) = app.path().resource_dir() {
        for candidate in [res.join("sidecar").join(SIDECAR_NAME).join(&exe), res.join("sidecar").join(&exe)] {
            if candidate.is_file() {
                return Ok(Launch::Exe(candidate));
            }
        }
    }
    // dev: walk up from the executable / cwd to find the repo (pyproject.toml + packages/)
    let mut probes = vec![std::env::current_dir().ok()];
    if let Ok(e) = std::env::current_exe() {
        probes.push(e.parent().map(|p| p.to_path_buf()));
    }
    for start in probes.into_iter().flatten() {
        let mut dir = Some(start.as_path());
        while let Some(d) = dir {
            if d.join("pyproject.toml").is_file() && d.join("packages").join("phewas_server").is_dir() {
                return Ok(Launch::Uv(d.to_path_buf()));
            }
            dir = d.parent();
        }
    }
    Err("phewas-server sidecar not found (bundle incomplete, and no development checkout nearby)".into())
}

fn show_error(win: &WebviewWindow, msg: &str) {
    let js = format!("window.__phewasError && window.__phewasError({});", serde_json::to_string(msg).unwrap_or_default());
    let _ = win.eval(&js);
}

fn start_sidecar(app: &AppHandle, win: WebviewWindow) -> Result<(), String> {
    let launch = resolve_sidecar(app)?;
    let tok = token();
    let log_dir = app.path().app_log_dir().map_err(|e| e.to_string())?;
    std::fs::create_dir_all(&log_dir).map_err(|e| e.to_string())?;
    let log_path = log_dir.join("phewas-server.log");

    let shell = app.shell();
    let cmd = match &launch {
        Launch::Exe(p) => {
            log::info!("starting bundled sidecar {}", p.display());
            shell.command(p).args(["--no-open", "--parent-pid", &std::process::id().to_string()])
        }
        Launch::Uv(root) => {
            log::info!("development mode: uv run phewas-server in {}", root.display());
            shell
                .command("uv")
                .args(["run", "phewas-server", "--no-open", "--parent-pid", &std::process::id().to_string()])
                .current_dir(root)
        }
    }
    .env("PHEWAS_TOKEN", &tok)
    .env("PYTHONUNBUFFERED", "1");

    let (mut rx, child) = cmd.spawn().map_err(|e| format!("could not start the data server: {e}"))?;
    app.state::<Sidecar>().0.lock().unwrap().replace(child);

    let app2 = app.clone();
    tauri::async_runtime::spawn(async move {
        use std::io::Write;
        let mut log = std::fs::File::create(&log_path).ok();
        let mut navigated = false;
        let started = std::time::Instant::now();
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) | CommandEvent::Stderr(bytes) => {
                    let line = String::from_utf8_lossy(&bytes).to_string();
                    if let Some(f) = log.as_mut() {
                        let _ = f.write_all(line.as_bytes());
                    }
                    if !navigated {
                        if let Some(url) = line.trim().strip_prefix("PHEWAS_URL=") {
                            if let Ok(u) = url.parse() {
                                navigated = true;
                                let _ = win.navigate(u);
                            }
                        }
                    }
                }
                CommandEvent::Terminated(status) => {
                    let msg = format!(
                        "The data server stopped (exit code {:?}). See the log: {}",
                        status.code,
                        log_path.display()
                    );
                    log::error!("{msg}");
                    if !navigated {
                        show_error(&win, &msg);
                    } else {
                        // the UI is gone with it; quit so the user can relaunch cleanly
                        app2.exit(1);
                    }
                    break;
                }
                CommandEvent::Error(e) => {
                    log::error!("sidecar error: {e}");
                }
                _ => {}
            }
            if !navigated && started.elapsed() > STARTUP_TIMEOUT {
                show_error(&win, "The data server did not start within 60 seconds.");
            }
        }
    });
    Ok(())
}

fn kill_sidecar(app: &AppHandle) {
    if let Some(child) = app.state::<Sidecar>().0.lock().unwrap().take() {
        let _ = child.kill();
    }
}

fn navigate(app: &AppHandle, hash: &str) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.eval(&format!("location.hash = {}", serde_json::to_string(hash).unwrap_or_default()));
    }
}

fn build_menu(app: &AppHandle) -> tauri::Result<tauri::menu::Menu<tauri::Wry>> {
    let import = MenuItemBuilder::with_id("import", "Import Dataset…").accelerator("CmdOrCtrl+I").build(app)?;
    let library = MenuItemBuilder::with_id("library", "Library").accelerator("CmdOrCtrl+L").build(app)?;
    let details = MenuItemBuilder::with_id("details", "Dataset Details").build(app)?;
    let reload = MenuItemBuilder::with_id("reload", "Reload").accelerator("CmdOrCtrl+R").build(app)?;
    let data_dir = MenuItemBuilder::with_id("data_dir", "Show Data Folder").build(app)?;
    let logs = MenuItemBuilder::with_id("logs", "Show Log Folder").build(app)?;

    let about = AboutMetadataBuilder::new()
        .name(Some("PheWAS Browser"))
        .version(Some(env!("CARGO_PKG_VERSION")))
        .authors(Some(vec!["Yiming Luo".to_string()]))
        .comments(Some("Research Use Only — contains sensitive data; do not disseminate."))
        .build();

    let mut menu = MenuBuilder::new(app);
    #[cfg(target_os = "macos")]
    {
        let app_menu = SubmenuBuilder::new(app, "PheWAS Browser")
            .item(&PredefinedMenuItem::about(app, Some("About PheWAS Browser"), Some(about.clone()))?)
            .separator()
            .services()
            .separator()
            .hide()
            .hide_others()
            .show_all()
            .separator()
            .quit()
            .build()?;
        menu = menu.item(&app_menu);
    }
    let file = SubmenuBuilder::new(app, "File")
        .item(&import)
        .item(&library)
        .item(&details)
        .separator()
        .item(&data_dir)
        .item(&logs)
        .separator()
        .close_window()
        .build()?;
    let edit = SubmenuBuilder::new(app, "Edit").undo().redo().separator().cut().copy().paste().select_all().build()?;
    let view = SubmenuBuilder::new(app, "View").item(&reload).separator().fullscreen().build()?;
    let window = SubmenuBuilder::new(app, "Window").minimize().maximize().separator().close_window().build()?;
    menu = menu.item(&file).item(&edit).item(&view).item(&window);
    #[cfg(not(target_os = "macos"))]
    {
        let help = SubmenuBuilder::new(app, "Help")
            .item(&PredefinedMenuItem::about(app, Some("About PheWAS Browser"), Some(about))?)
            .build()?;
        menu = menu.item(&help);
    }
    menu.build()
}

pub fn run() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    tauri::Builder::default()
        .manage(Sidecar(Mutex::new(None)))
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .menu(|app| build_menu(app))
        .on_menu_event(|app, event| {
            use tauri_plugin_opener::OpenerExt;
            match event.id().as_ref() {
                "import" => navigate(app, "#/import"),
                "library" => navigate(app, "#/library"),
                "details" => {
                    if let Some(win) = app.get_webview_window("main") {
                        let _ = win.eval("(function(){var m=location.hash.match(/^#\\/d\\/([^\\/]+)/); if(m) location.hash='#/d/'+m[1]+'/info';})()");
                    }
                }
                "reload" => {
                    if let Some(win) = app.get_webview_window("main") {
                        let _ = win.eval("location.reload()");
                    }
                }
                "data_dir" => {
                    if let Ok(dir) = app.path().app_data_dir() {
                        let _ = std::fs::create_dir_all(&dir);
                        let _ = app.opener().open_path(dir.to_string_lossy(), None::<&str>);
                    }
                }
                "logs" => {
                    if let Ok(dir) = app.path().app_log_dir() {
                        let _ = std::fs::create_dir_all(&dir);
                        let _ = app.opener().open_path(dir.to_string_lossy(), None::<&str>);
                    }
                }
                _ => {}
            }
        })
        .setup(|app| {
            let win = app.get_webview_window("main").expect("main window");
            if let Err(e) = start_sidecar(app.handle(), win.clone()) {
                log::error!("{e}");
                let w = win.clone();
                let msg = e.clone();
                // the loading page may not have run its script yet
                tauri::async_runtime::spawn(async move {
                    tokio_sleep(Duration::from_millis(600)).await;
                    show_error(&w, &msg);
                });
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::Destroyed = event {
                if window.label() == "main" {
                    kill_sidecar(window.app_handle());
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building the application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                kill_sidecar(app);
            }
        });
}

async fn tokio_sleep(d: Duration) {
    tauri::async_runtime::spawn_blocking(move || std::thread::sleep(d)).await.ok();
}
