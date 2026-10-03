# GUI Feature Inventory (PySide6 GUI, pre-removal)

Purpose: a complete, code-verified list of everything the PySide6 GUI does, so a web UI can
replace it without losing behaviour. Every statement below was read from the code at
commit `3148ad9`; where the GUI does **not** do something, it says so explicitly.

Paths below are relative to `src/thermalright_lcd_control/` unless they start with `resources/`.

Files covered: `main_gui.py`, `gui/main_window.py`, `gui/components/{controls_manager,preview_manager,config_generator}.py`,
`gui/tabs/{themes_tab,media_tab}.py`, `gui/widgets/{draggable_widget,thumbnail_widget}.py`,
`gui/utils/{config_loader,usb_detector}.py`, `resources/gui_config.yaml`, `resources/config/*.yaml`,
`resources/config/showcase/*.yaml`, `resources/themes/presets/*/*.yaml`,
`device_controller/display/{config,config_loader,frame_manager,text_renderer,generator,font_manager,utils,display_device}.py`,
`device_controller/metrics/*`, `common/supported_devices.py`, `device_init.py`.

---

## 1. Launch and GUI configuration file

### 1.1 Entry points
- `main_gui.py:main(config_file=None)`. Sets the Qt app name `thermalright-lcd-control`, display name
  `Thermalright LCD Control`, and desktop file name `thermalright-lcd-control.desktop`.
- Run as a script (`python main_gui.py --config <path>`), `--config` is **required** (argparse).
  `run_gui.sh` runs it with `--config ./resources/gui_config.yaml` from the repo root.
- Run through the console script `thermalright-lcd-control-gui` (pyproject `main_gui:main`), `main()` gets no
  argument, so `config_file` defaults to the literal relative path `"gui_config.yaml"` (resolved against the CWD).
- All relative paths in the config are resolved against the **process CWD**. `ThemesTab` explicitly does
  `Path(Path.cwd(), themes_dir)`. `install.sh` rewrites the `./resources/...` paths to absolute `$CONFIG_DIR/...` paths.

### 1.2 `gui_config.yaml` schema (`gui/utils/config_loader.py:load_config`, `get_default_config`)
| Key | Shipped value (`resources/gui_config.yaml`) | Built-in default if missing | Used by |
|---|---|---|---|
| `paths.themes_dir` | `./resources/themes/presets` | not in defaults; code falls back to `./themes` | ThemesTab, ConfigGenerator (theme save dir) |
| `paths.backgrounds_dir` | `./resources/themes/backgrounds` | `./themes/backgrounds` | Backgrounds tab |
| `paths.foregrounds_dir` | `./resources/themes/foregrounds` | `./themes/foregrounds` | Foregrounds tab |
| `paths.service_config` | `./resources/config` | not in defaults; ConfigGenerator falls back to `./config`; USBDeviceDetector has **no** fallback and returns None (fatal) | device_info.yaml lookup, Apply/Save target |
| `window.default_width` / `default_height` | 1920 / 1080 | 1000 / 600 (main_window falls back to 1200 / 600 if the key is absent after merge) | window geometry |
| `window.min_width` / `min_height` | 800 / 600 | 800 / 600 | window min size |
| `supported_formats.images` | `.jpg .jpeg .png .bmp .tiff .webp` | same | filters, type detection |
| `supported_formats.videos` | `.mp4 .avi .mkv .mov .webm .flv .wmv .m4v` | same | filters, type detection |
| `supported_formats.gifs` | `.gif` | same | filters, type detection |

Merge behaviour: a one-level "deep" merge. For a top-level dict key present in both, `dict.update` is used.
Note that `default_config.copy()` is shallow, so the defaults dict is mutated (harmless here). A missing file or a YAML error
logs a warning and uses the defaults.

### 1.3 Device detection (`gui/utils/usb_detector.py:USBDeviceDetector.find_connected_device`)
- **The GUI does NOT scan USB.** It reads `{paths.service_config}/device_info.yaml`, which is written by
  `device_init.py` (`python -m thermalright_lcd_control.device_init --config <config dir>`, run by `install.sh`).
  `device_init` does the actual USB scan (`usb.core.find` per VID/PID in `common/supported_devices.py`) and,
  if several devices match, asks the user to pick one on stdin.
- `device_info.yaml` keys: `class_name`, `width`, `height`, `vid`, `pid` (ints).
- Supported devices (`common/supported_devices.py`):
  | VID:PID | Resolution | Class |
  |---|---|---|
  | 0x0418:0x5304 | 480x480 | `hid_devices.DisplayDevice04185304` |
  | 0x0416:0x5302 | 320x240 | `hid_devices.DisplayDevice04165302` |
  | 0x87AD:0x70DB | 320x320 | `usb_devices.DisplayDevice87AD70DB320` |
  | 0x87AD:0x70DB | 480x480 | `usb_devices.DisplayDevice87AD70DB480` |
- If the file is missing or unreadable, `main_gui.py:show_error_and_exit` shows a modal critical box with the title
  "Error - No device found", the text "No supported device found.", and details listing every supported device as
  `• VID: 0x..., PID: 0x... (WxH)`. The GUI then exits with code 1.
- The window title is `ThermalRight LCD Control:  0x<vid>-0x<pid> | <W>x<H>` (`main_window.py:MediaPreviewUI.__init__`).
- Device `width`/`height` drive everything: preview size, the foreground sub-folder (`{foregrounds_dir}/{W}{H}`),
  the themes sub-folder (`{themes_dir}/{W}{H}`), and the service config file name (`config_{W}{H}.yaml`).
  The fallback is 320x240 if no device dict is given, but in practice the GUI exits before that.

---

## 2. Window layout (`main_window.py:setup_window`, `setup_ui`)
- Geometry: x=100, y=100, size `max(default, min)`. Minimum size is `max(min_width, W+580)` x `max(min_height, H+200)`.
- Layout is a vertical stack, despite the "Left/Right" comments:
  1. Top: a horizontal row with the **preview** (stretch 4) and the **controls scroll area** (stretch 6).
  2. Bottom: a **tab widget** with the tabs `Themes`, `Backgrounds`, `Foregrounds`, in that order.
- On close (`closeEvent`), it stops the date/time timers, calls `preview_manager.cleanup()`, and cleans up thumbnails.

---

## 3. Live preview (`gui/components/preview_manager.py:PreviewManager`)
- **Scaling: none, 1:1.** The preview is a `QLabel` of exactly W x H device pixels inside a fixed (W+4)x(H+4) frame
  with a 2px `#ccc` border and a white background. On-screen pixel coordinates equal device pixel coordinates.
- Initial text: "Initializing preview...".
- Rendering: `create_display_generator()` builds a `DisplayConfig` (`background_path`, a background type from
  `determine_background_type`, `output_width/height` = device W/H, `rotation`, `global_font_path` = Qt font family name
  (unused by the renderer), `foreground_image_path`, `foreground_position=(0,0)`, `foreground_alpha`) and a
  **new `DisplayGenerator`** (the same class the service uses). It is rebuilt on **every** change: background, foreground,
  opacity tick, or rotation.
- The preview generator has **no metrics, date, or time configs**. Text overlays in the preview are separate Qt
  `QLabel` widgets on top of the image (§8–§10), not PIL-rendered. Preview text can therefore differ slightly from the
  device output: Qt font rendering vs PIL `draw.text`, Qt label box vs PIL anchor.
- Frame loop (`update_preview_frame`): `get_frame_with_duration(apply_rotation=False)` → PIL → RGB → QPixmap.
  The next frame is scheduled with a single-shot `QTimer` at `max(int(duration*1000), 33)` ms (**minimum 33 ms, about 30 fps cap**).
- **Rotation is never applied to the preview** (`apply_rotation=False`). The preview always shows the unrotated canvas.
- Error texts are shown inside the preview label: "Error creating\nDisplayGenerator:\n<err>",
  "Error updating\npreview:\n<err>", "Error converting\nimage", "Background directory\nnot found",
  "No background files\nfound", and "Only images are supported\nfor foreground overlay".
- `determine_background_type(path)`: a falsy path gives `image`. A directory gives `image_collection`. An extension in
  `supported_formats.videos` gives `video`, in `gifs` gives `gif`, and anything else gives `image`.
- `clear_background` / `clear_foreground` / `clear_all` / `initialize_default_background` exist (falling back to
  the first supported file in `backgrounds_dir`, in `iterdir()` order), and `main_window` has `clear_*` handlers,
  **but no button or menu is wired to them. They are unreachable from the UI.**

---

## 4. Background media rendering (`device_controller/display/frame_manager.py:FrameManager`)
Shared by the preview and the service. Behaviour per `background.type`:

| Type | Load | Frame timing | Edge cases |
|---|---|---|---|
| `image` | `Image.open`, then resized to exactly W x H with LANCZOS (**stretch, aspect ratio NOT preserved**), then RGBA | single frame; `frame_duration` = `DEFAULT_FRAME_DURATION` = **2.0 s** (re-render interval) | missing file raises `FileNotFoundError` |
| `gif` | every frame via `ImageSequence`, each resized and stretched | per-frame `frame.info['duration']` ms / 1000; **default 100 ms** if absent; 0.1 s on exception | duration 0 means it advances on every call. The preview clamps to 33 ms minimum; the service sleeps `max(0, d - render_time)` |
| `video` | **all frames decoded into memory** with OpenCV, BGR to RGB, resized and stretched | `1/fps`; **fallback 1/30 s** if fps ≤ 0 | needs `cv2`. Without OpenCV, or for an extension not in the hard-coded video list, it falls back to loading the path as a static image (will usually fail). No audio. Loops forever. Large videos use a lot of RAM |
| `image_collection` | path must be a directory. Globs `*.jpg *.jpeg *.png *.bmp *.tiff *.webp` plus their UPPERCASE variants, sorted alphabetically | **fixed 2.0 s per image** (`DEFAULT_FRAME_DURATION`), **not configurable** in YAML or UI | mixed-case extensions such as `.Png` are skipped. **GIFs and videos inside a collection are ignored.** No images raises `RuntimeError("No images found in directory")` |

Frame advance (`get_current_frame`): wall-clock based. If `now - frame_start >= frame_duration`, it advances the index
(mod N). For a GIF, `frame_duration` is then set to the duration of the *new* current frame.

`get_current_frame_info` references a non-existent `self.wait_duration` (would raise `AttributeError`). It is unused by the GUI.

---

## 5. Foreground overlay and opacity
- **Selection** (`main_window.py:on_foreground_clicked`): clicking a thumbnail in the Foregrounds tab sets the foreground
  if its extension is in `supported_formats.images` **or** is `.gif`. Anything else shows "Only images are supported for
  foreground overlay" in the preview. (The Foregrounds tab only lists `images` extensions, so `.gif` never appears there.)
- **Compositing** (`generator.py:DisplayGenerator._add_foreground_image`): the image is opened and converted to RGBA.
  If `alpha < 1.0`, its existing alpha channel is multiplied by `alpha` (`p * alpha`). It is then pasted at
  `foreground_position` using its own alpha as mask. **It is not resized.** The assets are already per-resolution
  (`foregrounds/{W}{H}/`). If the file is missing, the foreground is silently skipped. A GIF foreground uses only its first frame.
- **Position:** always `(0,0)`. The GUI writes `foreground.position: {x:0, y:0}` and has no control for it.
- **Opacity control** (`controls_manager.py:_create_opacity_controls`): an untitled group with "Opacity:" and a value label `N%`, plus a
  horizontal `QSlider` from 0 to 100, default **50**, ticks every 10.
  - `valueChanged` updates the `%` label and calls `main_window.on_opacity_text_changed(str(v))`, which calls
    `preview_manager.set_foreground_opacity(v/100)` and rebuilds the generator on every tick.
  - `sliderReleased` calls `on_opacity_editing_finished`. **Edge case: if the value is 0, it resets to 50% (0.5)**
    (`if not value`). Otherwise it clamps to 0–100 and re-sets the value.
  - The internal default `PreviewManager.foreground_opacity` is `0.5`.
- Opacity applies only to the foreground. There is **no background opacity**.
- **Removing the foreground is not possible in the UI.** There is no "none" or clear button. `clear_foreground` is unwired.
  Loading a theme whose `foreground.enabled: false` does **not** clear a previously set foreground (see §11.3).
- The foreground path is written with a resolution placeholder: `config_generator.py:_add_resolution_placeholder`
  replaces the substring `/{W}{H}/` with `/{resolution}/`. On load it is expanded back with
  `.format(resolution=f"{W}{H}")` (both `main_window.on_theme_selected` and `ConfigLoader`).

---

## 6. Rotation
- Control: group "Display Rotation", label "Rotation:", combo box with items `0°`, `90°`, `180°`, `270°`
  (data 0/90/180/270). Default 0 (`controls_manager.py:_create_rotation_controls`).
- On change: `main_window.on_rotation_changed` → `preview_manager.set_rotation` (generator rebuilt, but the preview stays unrotated).
- YAML key `display.rotation` (int). Any other value is accepted by the loader but means "no rotation" in the generator.
- Device-side semantics (`generator.py:generate_frame_with_metrics`, `apply_rotation=True` in the service):
  rotation is **clockwise**. 90 uses PIL `ROTATE_270`, 180 uses `ROTATE_180`, and 270 uses `ROTATE_90`. Rotation is applied to the
  final composed image. **The canvas is not re-dimensioned**: for 320x240 at 90°, layout coordinates are still in a
  320-wide by 240-high space, and the rotated image is sent as is. All x/y positions are in the unrotated canvas.
- On theme load, the combo is set via `findData(rotation)`. An unknown value leaves the combo unchanged, but the preview manager still
  stores it.

---

## 7. Text style (global): font, size, colour, bold (`gui/widgets/draggable_widget.py:TextStyleConfig`)
- **One global style** shared by the date, time, and all metric widgets: `font_family`, `font_size` (default **18**),
  `color` (default **black `QColor(0,0,0)`**), `bold=True`.
- **Font:** not user-selectable. The preview uses the family `fc-match ":weight=bold" --format=%{fullname}`
  (`display/utils.py:_get_default_font_name`). The device uses the font **file** from
  `fc-match ":weight=bold" --format=%{file}` (`font_manager.py:SystemFontManager`), loaded with
  `ImageFont.truetype(path, size)` and cached per size. The fallbacks are `ImageFont.load_default(size)`, or `load_default()` with no size
  if the path is empty. If `fc-match` fails, the value is the string `"Not available"`. There is **no font-family or bold key in the YAML**.
  `DisplayConfig.global_font_path` is set by the preview but **ignored** by `TextRenderer`.
- **Size:** group "Text Style", label "Size:", `QSpinBox` with range **8–72**, initial 18. Qt applies it as CSS `font-size: Npx`.
  PIL uses it as the truetype size. Changing it calls `on_font_size_changed`, which re-styles **all** overlay widgets.
- **Colour:** label "Choose Colors:" with a swatch button (background = colour; text black if lightness > 128, else white).
  Clicking opens `QColorDialog.getColor(current)` **without the alpha-channel option**, so the user cannot pick alpha. The
  chosen colour has alpha 255 and is applied to **all** overlay widgets.
- Colour format in YAML is `#RRGGBBAA` uppercase hex (`config_generator.py:_qcolor_to_hex`). On read, `#RRGGBB`
  (alpha 255) and `#RRGGBBAA` are both accepted. Other lengths raise `ValueError` (`config_loader.py:_hex_to_rgba`) or are
  logged and ignored (`main_window.hex_to_qcolor`). The `#` is optional on read.
- The preview renders `color.name()` (`#rrggbb`), so **alpha is ignored in the preview**. The device honours alpha in `draw.text` fill.
- Per-element sizes and colours **are** stored per item in the YAML and honoured by the device renderer, but the GUI:
  - on load: date and time each overwrite the *global* style (time is applied last and wins). Metrics with
    `font_size`/`color` get a per-widget style copy (`apply_metrics_config`). Then `update_controls_from_widgets`
    sets the size spinbox. If that changes the value, `valueChanged` re-applies the global style to all widgets,
    discarding per-metric styles in the preview.
  - on save: **every** item (date, time, each metric) is written with the single global `font_size` and `color`.
    Per-item styling in a loaded theme is therefore lost when re-saved from the GUI.

---

## 8. Date and time overlays
- Widgets: `DateWidget` (format `%d/%m`, e.g. `03/10`) and `TimeWidget` (format `%H:%M`, 24-hour), from `draggable_widget.py`.
- Formats are **fixed**. There is no UI or YAML key to change them, and no 12-hour, seconds, weekday, or year option. The device renderer
  hard-codes the same formats (`text_renderer.py:render_date`, `render_time`). It uses local time (`datetime.now()`).
- Checkboxes in group "Overlay Widgets": "Show Date" (initially **checked**) and "Show Time" (initially unchecked).
  Initial widget positions: date (200,10), time (200,40). Initial enabled state: date on, time off.
- **Preview edge case:** the timer fires every 1000 ms but only re-sets the text cached at construction. The preview
  date and time are **frozen at GUI start time** and do not tick. The device output is live.
- YAML (`display.date`, `display.time`): `enabled` (bool), `position.x`/`position.y` (int px, top-left),
  `font_size` (int), `color` (`#RRGGBBAA`), `text` (always written as `""`; **unused** by the renderer for
  date/time. `render_custom_text` exists but is never called). The ConfigGenerator fallback positions (310,15)/(310,35)
  are used only if a widget object is missing, which never happens in practice.
- Disabled date/time are still written with their last position.

---

## 9. Hardware metrics overlays
### 9.1 Metric set (fixed: exactly six; `main_window.py:create_overlay_widgets`)
| `name` (YAML) | Checkbox group / text | Label placeholder | Unit placeholder | Initial preview pos | Source / unit of raw value |
|---|---|---|---|---|---|
| `cpu_temperature` | CPU Metrics / "Temp" | `CPU` | `°` | (10,40) | `CpuMetrics.get_temperature()`, °C float (hwmon Tdie/Tctl, psutil, thermal zones) |
| `cpu_usage` | CPU Metrics / "Usage" | `CPU%` | `%` | (10,100) | `psutil.cpu_percent(interval=0)`, % |
| `cpu_frequency` | CPU Metrics / "Frequency" | `CPU` | `MHZ` | (10,160) | psutil / sysfs `scaling_cur_freq` / `/proc/cpuinfo`, MHz rounded to 2 dp |
| `gpu_temperature` | GPU Metrics / "Temp" | `GPU` | `°` | (10,70) | `GpuMetrics`, °C |
| `gpu_usage` | GPU Metrics / "Usage" | `GPU%` | `%` | (10,130) | `GpuMetrics`, % |
| `gpu_frequency` | GPU Metrics / "Frequency" | `GPU` | `MHZ` | (10,190) | `GpuMetrics`, MHz |

The service also collects `gpu_vendor` and `gpu_name` (`frame_manager._get_current_metric`), but they are **not offered in the GUI**.
Per-core, RAM, NVMe, power, and fan metrics do **not** exist in the GUI or theme renderer. They exist only in the separate
`showcase` layout (§14).

### 9.2 Controls (`controls_manager.py:_create_overlay_controls`, `_create_metric_layout`)
Per metric: a checkbox (initially unchecked), "Label:" `QLineEdit` (max width 60), and "Unit:" `QLineEdit` (max width 40).
- Placeholders show the defaults above, but **the placeholders are NOT used as values**. An empty field means an empty label/unit.
- Typing calls `on_metric_label_changed` / `on_metric_unit_changed` (text is `.strip()`ped) and updates the widget immediately.
- Checkbox styling adapts to a dark or light Qt palette (`_get_smart_checkbox_style`). This is cosmetic.

### 9.3 Display text and format
- Preview text (`MetricWidget`): `"{label}{value}{unit}"`, where label = `"<label>: "` if non-empty, otherwise `""`, and value =
  `metric.get_metric_value(name)` as a raw string (e.g. `45.0`, `3600.12`), or `N/A`.
- **Preview edge case:** the value is computed only at construction and when the label or unit changes. The 1 s timer does not
  refresh it, so **preview metric values are static snapshots**.
- YAML item (`display.metrics.configs[]`), as written by the GUI (`config_generator.py:generate_config_data`):
  `name`, `label` (string, without ": "), `enabled` (true), `position.x`/`.y` (int px), `font_size` (global),
  `color` (global `#RRGGBBAA`), `format_string` (always `"{label}{value}{unit}"`), `unit` (string).
  **Only enabled metrics are written.** `display.metrics.enabled` = any metric enabled.
- Device rendering (`text_renderer.py:render_metrics`):
  - `format_string` placeholders: `{label}` (the label followed by ": " if non-empty), `{value}`, `{unit}`. The loader default if the key is
    absent is `"{label}{value}"`. `{value:.0f}` and `{value:.1f}` are supported (the value is converted to float). Other
    format specs go through `str(value)`.
  - **A metric whose value is `None` is not drawn at all** on the device. The preview shows `N/A`. Example: no GPU detected.
  - On a formatting error, the fallback text is `"<label>: <value><unit>"`.
  - Device metrics refresh every **5.0 s** (`FrameManager.REFRESH_METRICS_INTERVAL`, a `threading.Timer` chain). This is **not configurable**.
    The first sample is taken at generator construction.
  - The metric sampler thread runs only if at least one metric is enabled.
- Shipped presets/configs use units `°`, `°C`, `MHZ`, font sizes 24/27, colour `#FFFFFFFF`, and only the four metrics
  cpu/gpu temperature and frequency.

---

## 10. Drag positioning and coordinate system (`draggable_widget.py:DraggableWidget`)
- Each overlay (date, time, six metrics) is a `QLabel` child of the preview widget. Left-button drag moves it.
  The cursor is an open hand on hover and a closed hand while dragging.
- The new position is `pos + (mouse - press offset)`, **clamped** so the whole label box stays inside the preview
  (`0 ≤ x ≤ W - label_width`, `0 ≤ y ≤ H - label_height`). It emits `positionChanged` (no subscriber).
- **Coordinates:** integer device pixels, origin at the top-left of the **unrotated** canvas, and they mark the **top-left of the
  label box**. The device draws with PIL `draw.text((x,y))` (default anchor `la`, top-left of text ascender), so
  vertical placement can differ by a few px from Qt's label box (padding 0, centred alignment, size = `adjustSize`).
- Disabled widgets have empty text and are `setDisabled(True)`, so they cannot be dragged, but they keep their position.
- There is no snapping, grid, alignment, keyboard nudging, numeric x/y entry, or z-order control. Draw order on the device is:
  background, then foreground, then metrics (YAML order), then date, then time.

---

## 11. Themes tab (`gui/tabs/themes_tab.py:ThemesTab`)
### 11.1 Listing
- Directory: `Path.cwd() / {paths.themes_dir} / {W}{H}` (e.g. `resources/themes/presets/320240`). It is created
  (`mkdir -p`) if missing, and the list is then empty with no message.
- Files: `*.yaml` and `*.yml` (non-recursive), **sorted by mtime, newest first**.
- Header: "Available Themes" (14pt bold) and a **Refresh** button (`refresh_themes`, which reloads the list).
- Empty: "No theme files found in themes directory".
- Grid: **8 columns**, `ThumbnailWidget` 120x100 with a 2px blue `#0078d4` border, and a 3px `#005a9e` border with a `#e3f2fd` background on hover.
- Display name (`get_theme_display_name`): file stem with `_` and `-` replaced by spaces, each word capitalised
  (`config_20251003_101500` becomes `Config 20251003 101500`).
- **Thumbnail** = the theme's background, not a rendered composite. No foreground or text is shown (`get_theme_background_info`
  parses with `ConfigLoader.load_config`; `get_thumbnail_path`): image is scaled; GIF is animated; video shows the frame at 10%;
  `image_collection` shows the first image (alphabetical, same glob as FrameManager). If the theme fails to parse (e.g.
  missing required keys) or the file does not exist, the placeholder shows "?".
- Shipped presets: `320240/config_1..6.yaml` (two are `video`: `d025.mp4`, `a001.mp4`), `320320/config_1.yaml`,
  `480480/config_1.yaml`.

### 11.2 Auto-load on startup
`MediaPreviewUI.setup_ui` calls `themes_tab.auto_load_first_theme()`, which loads the **most recently modified theme**
for this resolution. If there are none, the preview stays at "Initializing preview...".

### 11.3 Loading a theme (`main_window.py:on_theme_selected`): a click on a theme thumbnail
1. Parses the YAML with `yaml.safe_load` (not via ConfigLoader).
2. `display.rotation` (default 0) is set in the combo and the preview.
3. `display.background.path`, if non-empty, calls `set_background(path)`. **`background.type` from the file is ignored.** The type is
   re-derived from the extension or directory.
4. If `display.foreground.enabled`: the path is formatted with `{resolution}`, then `set_foreground` and
   `set_foreground_opacity(alpha)` (default 1.0) are called, and the slider is set to `int(alpha*100)`. **If foreground is disabled or absent, nothing is
   cleared**: the previous foreground and opacity remain.
5. `display.date` / `display.time` (if present and non-empty): `enabled`, `position` (keeps the current value if the key is absent),
   `font_size` and `color` go into the **global** text style.
6. `display.metrics.configs` (if present): all six metrics are disabled first, then each listed `name` is applied
   (`enabled`, `position`, `label`, `unit`, per-metric `font_size`/`color`). Unknown names are skipped.
   `format_string` is **not read** by the GUI. If the theme has no `metrics.configs`, the previous metric states remain.
7. `update_controls_from_widgets`: syncs the checkboxes. Label and unit fields are updated **only for enabled metrics**.
   The size spinbox and colour swatch are updated too.
8. Any exception shows a "Theme Load Error" warning box: "Failed to load theme:\n<err>".

Themes cannot be renamed, deleted, duplicated, exported, or imported through the GUI.

---

## 12. Save and Apply (`controls_manager.py:_create_action_controls`, `config_generator.py:ConfigGenerator`)
Two green buttons (100x35), right-aligned: **Save** and **Apply**.

| Button | Handler | Writes |
|---|---|---|
| **Apply** | `main_window.generate_preview` → `generate_config_yaml(preview=True)` | **only** the service config `{paths.service_config}/config_{W}{H}.yaml` |
| **Save** | `main_window.generate_config_yaml` → `generate_config_yaml(preview=False)` | the service config (as above) **and** a new theme `{paths.themes_dir}/{W}{H}/config_YYYYMMDD_HHMMSS.yaml`, then refreshes the Themes tab |

- How "Apply" reaches the LCD: the service (`display_device.py:DisplayDevice._get_generator`) checks the
  config file's `st_mtime_ns` once per frame and rebuilds its generator when it changes. There is no IPC, signal, or service restart.
- Files are written with `yaml.dump(default_flow_style=False, allow_unicode=True, indent=2)`, so keys are sorted alphabetically.
  The write is **not atomic** (the file is opened with `'w'` directly). The service config is written first. If the themes dir does not exist, the
  theme write fails after the service config was already updated.
- **No user feedback**: no success or failure dialog. Errors are only logged (`get_gui_logger`).
- No overwrite of an existing theme. There is always a new timestamped file, and the user cannot name it.
- **Edge case (Vigyan packaging):** the GUI rewrites the whole service config with only the `display:` tree. It
  **drops the `showcase:` and `telemetry:` blocks** present in `resources/config/showcase/config_*.yaml`. So pressing
  Apply or Save turns the showcase dashboard off and removes telemetry settings. The header comment in that file
  acknowledges this ("or let the GUI rewrite this file").
- Generated `display` tree (exact shape):
```yaml
display:
  rotation: 0|90|180|270
  background:
    path: <current background path or "">      # file or collection directory, path as browsed (relative if paths.* are relative)
    type: image|gif|video|image_collection     # derived from extension/dir
  foreground:
    enabled: <bool: a foreground is set>
    path: <path with /{W}{H}/ replaced by /{resolution}/, or null>
    position: {x: 0, y: 0}
    alpha: <float 0.0–1.0, slider/100>
  metrics:
    enabled: <any metric enabled>
    configs:                                   # enabled metrics only, insertion order cpu_temperature, gpu_temperature, cpu_usage, gpu_usage, cpu_frequency, gpu_frequency
      - name: <metric name>
        label: <string>
        enabled: true
        position: {x: <int>, y: <int>}
        font_size: <global size>
        color: '#RRGGBBAA'
        format_string: '{label}{value}{unit}'
        unit: <string>
  date: {enabled: <bool>, position: {x, y}, font_size: <global>, color: '#RRGGBBAA', text: ''}
  time: {enabled: <bool>, position: {x, y}, font_size: <global>, color: '#RRGGBBAA', text: ''}
```
- If no background was ever set, `path: ""` and `type: image` are written. The service then fails with `FileNotFoundError`.
- Required keys for the service loader (`config_loader.py:load_config_from_dict`), which raise `KeyError` if missing:
  `display.metrics.enabled`, `display.date.enabled`, `display.time.enabled`, `display.foreground.enabled`,
  `display.background.path`, `display.background.type`; per enabled metric: `name`, `position.x/y`, `font_size`, `color`;
  per enabled date/time: `position.x/y`, `font_size`, `color`; for an enabled foreground: `path`, `position.x/y`, `alpha`.
  Optional with defaults: `rotation` (0), metric `label` (""), `format_string` (`"{label}{value}"`), `unit` (""),
  metric `enabled` (true), text `text` (""), text `enabled` (true).

---

## 13. Media tabs: Backgrounds and Foregrounds (`gui/tabs/media_tab.py:MediaTab`)
### 13.1 Browsing
- Backgrounds dir: `{paths.backgrounds_dir}` (flat, **shared across resolutions**; ships 282 PNG and 16 MP4 files).
  Foregrounds dir: `{paths.foregrounds_dir}/{W}{H}` (110 PNG files for 320240, 120 each for 320320 and 480480).
- Listed entries: files whose lowercase extension is supported (Backgrounds: images, videos, and GIFs; Foregrounds: **images
  only**), plus, in any tab, sub-directories whose name starts with `collection_`.
- Sort (`sort_files_user_first`): user-added entries first (names starting with `user_` or `collection_`), then the rest. Each group is sorted
  case-insensitively by name.
- Display name: the `user_` prefix is stripped (`get_display_name`). Collection labels read "Collection (N images)" with the path in the tooltip.
- Grid of **8 columns**. File tiles are `ThumbnailWidget`. Collection tiles are a 100x100 button with the first image (iterdir order,
  extensions `.jpg .jpeg .png .bmp .gif` only) scaled to 96x96. A collection with no such images returns `None`, and adding `None` to the
  grid raises an error that is caught by the outer `except`, so the **whole tab shows the error label**.
- User-added files get a green border stylesheet (`QFrame` selector; it targets QFrame, so it may not visibly apply to the
  QWidget-based tile).
- Messages (partly in **French**): an empty directory shows "Aucun média trouvé dans:\n<dir>\n\nFormats supportés:\n…" in orange.
  A missing directory shows "Répertoire média introuvable: … Veuillez vérifier le paramètre '<tab>_dir' …" in red. A load error shows
  "Erreur lors du chargement des médias: …".
- A click on a background tile calls `on_background_clicked` and `set_background(path)`. A click on a collection tile passes the directory path
  (type `image_collection`). A click on a foreground tile is handled as in §5.
- There is no search, filter, pagination, or file-type badge. There is no delete, rename, or reveal-in-folder for media.

### 13.2 Import ("Add Media", Backgrounds tab only; `add_media_files`)
- A button "Add Media" (max width 150) opens a native multi-select dialog titled "Select one or more media files for Backgrounds",
  with filter `Media files (*.ext …)` built from all background extensions.
- **One file:** if the extension is unsupported, a warning "Unsupported Format" lists the supported formats. Otherwise `copy_media_file`:
  `mkdir -p` the backgrounds dir, copy with `shutil.copy2` (preserves mtime and metadata) to `user_<stem><ext>`. On a name clash it
  uses `user_<stem>_1<ext>`, `_2`, and so on. An info box "Media Added" says "File '<src>' was successfully added as '<dest>'." The tab reloads, the new file
  is **auto-applied as the background**, and `media_added` is emitted (no subscriber).
- **Several files**, which creates a collection (`create_collection_from_files`): unsupported files produce an "Unsupported formats" warning listing the first 5 names
  plus "... and N others", and are skipped. If none remain, it aborts silently. It creates `collection_<8 hex of uuid4>/` in
  the backgrounds dir and copies each file as `user_<name>` (same clash rule). It shows an info box "Created collection" with the count and dir
  name, reloads, and the `collection_created` signal **auto-applies the collection as the background**.
  Edge cases: videos and GIFs *can* be copied into a collection but are ignored at render time. A collection of only videos fails
  to render ("No images found"). The collection cycle interval is fixed at **2 s**. Image order is alphabetical by the `user_`-prefixed name.
- Errors: "Error" / "Error adding media:\n…", "Copy Error" / "Unable to copy file:\n…", and "Erreur" / "Error creating collection:\n…".
- Foregrounds **cannot** be imported through the GUI. There is no file-size, dimension, or duplicate-content check, and no transcoding.

---

## 14. Thumbnails (`gui/widgets/thumbnail_widget.py:ThumbnailWidget`)
- Tile 120x100, white, 1px `#ddd` border with radius 5, and a 2px `#0078d4` border with a `#f0f0f0` background on hover. Content area 110x70, filename label 10px with word-wrap.
- Image (`.jpg .jpeg .png .bmp .tiff .webp`, hard-coded): `QPixmap` scaled to 110x70 keeping aspect ratio, smooth. If it fails: "Image\nUnavailable".
- GIF: animated `QMovie` scaled to **exactly** 110x70 (aspect ratio not kept). If it fails: "GIF\nUnavailable" or "GIF\nError".
- Video (`.mp4 .avi .mov .mkv .wmv .flv .m4v .webm`): OpenCV grabs the frame at `frame_count // 10` (if there are more than 10 frames), scaled
  keeping aspect ratio. Without OpenCV, or on error: a dark `#2c3e50` tile with "📹\nVIDEO". There is no inline playback (the QVideoWidget is unused).
- Any other extension, or an empty path: "?". An exception: "Error".
- Left-click emits `clicked(file_path)`. There is no selected or active-state highlight anywhere in the GUI.

---

## 15. Settings that do NOT exist (state explicitly for the web UI spec)
- **Brightness / backlight:** not present anywhere in the GUI, YAML, or device code (grep for "bright" finds nothing).
- **Frame rate / refresh rate / FPS cap:** no setting. Frame timing comes only from the media (GIF metadata, video
  fps, fixed 2 s for images and collections). The preview minimum is 33 ms.
- **Metrics refresh interval:** fixed at 5 s on the device. The preview is static. No setting.
- **Image collection interval:** fixed at 2 s. No setting.
- **Font family / bold / italic / alignment / shadow / outline:** no setting (bold system font via fc-match).
- **Per-element font size or colour in the GUI:** no (global only; see §7).
- **Colour alpha picker:** no (dialog without alpha; always written as `FF`).
- **Date or time format choice:** no (`%d/%m`, `%H:%M`).
- **Custom free text:** no (`text` key written empty; `render_custom_text` is never called).
- **Foreground position, scale, or removal:** no.
- **Background fit mode (fit/fill/crop):** no (always stretched to W x H).
- **Video audio, trim, or start offset:** no.
- **Device selection or switching in the GUI:** no (comes from `device_info.yaml`). There is no hot-plug detection, connection status, or
  service start/stop/status control.
- **Showcase layout settings** (`showcase.enabled`, `refresh_seconds`, `title`, `temp_warn`, `temp_crit`,
  `rotation`) and **telemetry settings** (`telemetry.enabled`, `otlp_endpoint`, `interval_seconds`): not exposed, and
  erased by Apply or Save (§12).
- **Undo/redo, unsaved-changes prompt, theme rename/delete, media delete:** no.

---

## 16. Behavioural quirks and bugs found (decide: preserve, fix, or drop)
1. Preview date, time, and metric values never update after creation (§8, §9.3).
2. Releasing the opacity slider at 0% snaps it back to 50% (§5).
3. A foreground cannot be removed. Loading a theme with the foreground disabled keeps the old one (§5, §11.3).
4. Theme `background.type` is ignored on load and re-derived (§11.3). `metrics.format_string` is ignored on load and always
   re-written as `{label}{value}{unit}` (§9.3).
5. Per-item font size and colour collapse into one global style on save. On load, time overrides date's style (§7).
6. Loading a theme without `metrics.configs` / `date` / `time` keeps the previous state of those widgets (§11.3).
7. Label and unit inputs of disabled metrics are not refreshed on theme load (§11.3).
8. Apply and Save erase `showcase:`/`telemetry:` from the service config (§12).
9. There is no success or failure feedback on Save/Apply. The writes are non-atomic, and the service config is written before the theme file (§12).
10. A collection directory containing no `.jpg/.jpeg/.png/.bmp/.gif` breaks the whole Backgrounds tab listing (§13.1).
11. Collection thumbnails count `.gif` but not `.tiff/.webp`, while the renderer is the inverse (§4, §13.1).
12. `DisplayGenerator.cleanup` is decorated as `@async_background` without parentheses, so calling it only returns a
    function and **never runs** (verified). The previous generator's metric timer thread is not cancelled on rebuild.
    The preview builds generators without metrics, so it has no thread. It matters for a long-running server that rebuilds generators.
13. `FrameManager.get_current_frame_info` references an undefined `wait_duration` (unused).
14. The preview is never rotated, and the device canvas is not re-dimensioned when rotated (§6).
15. Preview text placement is Qt-based while the device uses PIL, so they may differ by a few pixels (§10).
16. Some user-facing strings are in French (§13.1).

---

## 17. Checklist: Feature | Web UI equivalent needed

| # | Feature | Web UI equivalent needed |
|---|---|---|
| 1 | Load GUI config (`paths.*`, `window.*`, `supported_formats.*`) with defaults and CWD-relative paths | Server reads same `gui_config.yaml` (or equivalent) with same defaults/path resolution |
| 2 | Device identity from `{service_config}/device_info.yaml` (vid, pid, width, height, class_name) | API endpoint returning device info; UI header "0xVID-0xPID \| WxH" |
| 3 | "No device found" error listing all supported VID:PID (WxH) | Error page/banner listing `SUPPORTED_DEVICES` |
| 4 | Resolution-scoped folders (themes `{W}{H}`, foregrounds `{W}{H}`, `config_{W}{H}.yaml`) | Same path derivation server-side |
| 5 | Live preview at 1:1 device pixels (W x H), white frame | Canvas/img at native W x H (optionally zoomable, but coordinates in device px) |
| 6 | Preview rendered by the real `DisplayGenerator` (background + foreground), unrotated | Server-rendered frame endpoint/stream using `DisplayGenerator` (`apply_rotation=False`), or the same compositing in browser |
| 7 | Animated preview timing: GIF per-frame ms (default 100), video 1/fps (fallback 1/30), image/collection 2 s, min 33 ms | Frame stream (MJPEG/WebSocket/polling) honouring `frame_duration`, ≥33 ms |
| 8 | Background type detection (dir→image_collection, video/gif/image by extension) | Same rule server-side |
| 9 | Background types image / gif / video / image_collection, stretched to W x H | Same renderer; document stretch behaviour |
| 10 | Image collection cycling, alphabetical, fixed 2 s, image-only, case rules | Same (optionally note interval not configurable) |
| 11 | Foreground selection from `foregrounds/{W}{H}` (images; .gif accepted on click) | Foreground picker grid |
| 12 | Foreground compositing at (0,0), alpha multiplies PNG alpha, not resized | Same server compositing |
| 13 | Foreground opacity slider 0–100 %, default 50, written as `alpha` 0.0–1.0, live preview | Slider with live preview (decide on 0 → 50 quirk) |
| 14 | Foreground path stored with `{resolution}` placeholder, expanded on load | Same path templating on save/load |
| 15 | Rotation selector 0/90/180/270 (clockwise on device, preview unrotated, canvas not resized) | Rotation select; preview optionally shows rotated view; save `display.rotation` |
| 16 | Global font size 8–72 applied to all overlays | Number input 8–72 |
| 17 | Global colour picker (no alpha in dialog), stored `#RRGGBBAA` uppercase, read `#RRGGBB`/`#RRGGBBAA` | Colour input producing `#RRGGBBAA` (optionally with alpha) |
| 18 | System bold font via `fc-match :weight=bold` (no font choice) | Server renders text (or preview uses server-rendered overlays) so font matches device |
| 19 | Date overlay `%d/%m`, toggle (default on), draggable, default pos (200,10) | Toggle + draggable element; live clock |
| 20 | Time overlay `%H:%M`, toggle (default off), draggable, default pos (200,40) | Toggle + draggable element; live clock |
| 21 | Six metrics (cpu/gpu × temperature/usage/frequency) with checkboxes | Six toggles grouped CPU/GPU |
| 22 | Per-metric custom label (rendered `label: `) and unit, placeholders CPU/GPU/CPU%/GPU%, °/%/MHZ | Text inputs with same placeholders; empty = empty |
| 23 | Metric default preview positions (10,40)…(10,190) | Same defaults |
| 24 | Metric value source/units (°C, %, MHz) and `N/A` / skip-when-None | Live values endpoint; preview shows N/A, device skips None |
| 25 | `format_string` support (`{label}{value}{unit}`, `{value:.0f}`, `{value:.1f}`) | Preserve key on load/save (GUI always wrote default) |
| 26 | Device metric refresh 5 s (fixed) | Document; no setting needed unless added |
| 27 | Drag-to-position overlays, clamped to canvas, integer px top-left in unrotated canvas | Pointer drag with clamping; optional numeric x/y |
| 28 | Themes tab: list `*.yaml`/`*.yml` in `{themes_dir}/{W}{H}`, newest-mtime first, Refresh | Theme gallery with refresh, same sort |
| 29 | Theme display name from filename (`_`/`-`→space, Title Case) | Same naming |
| 30 | Theme thumbnails from background (image/GIF/video 10% frame/collection first image, "?" fallback) | Thumbnail endpoint with same rules (cache) |
| 31 | Auto-load most recent theme at startup | Load newest theme into editor on open |
| 32 | Load theme into editor (rotation, background, foreground+alpha, date/time, metrics incl. label/unit/size/colour) | Same mapping; decide on stale-state quirks (§16.3, 6, 7) |
| 33 | Theme load error dialog "Failed to load theme" | Error toast |
| 34 | Apply: write `{service_config}/config_{W}{H}.yaml` → service hot-reloads by mtime | "Apply to LCD" button calling API that writes same file (prefer atomic write) |
| 35 | Save: Apply + new theme `config_YYYYMMDD_HHMMSS.yaml` + refresh list | "Save as theme" (optionally named) + apply |
| 36 | Generated YAML shape and required keys (§12) | Same serializer; validate against loader's required keys |
| 37 | Apply/Save drop `showcase:`/`telemetry:` blocks | Decide: preserve them (merge) and/or expose showcase/telemetry settings |
| 38 | Backgrounds grid (shared dir, images+videos+GIFs+`collection_*` dirs), user-added first, `user_` prefix hidden | Media gallery with same filter/sort/naming |
| 39 | Foregrounds grid (`{W}{H}` dir, images only) | Foreground gallery |
| 40 | Add Media (backgrounds only): single file → copy as `user_<name>` (+`_N` on clash), auto-apply | Upload endpoint with same naming, then auto-select |
| 41 | Multi-file add → `collection_<8hex>/` with `user_` files, skip unsupported (warn first 5), auto-apply | Multi-upload → collection creation, same rules |
| 42 | Unsupported-format warning listing supported extensions | Client + server validation messages |
| 43 | Success/info dialogs ("Media Added", "Created collection") and copy errors | Toasts |
| 44 | Media thumbnails (image scaled, animated GIF, video frame at 10%, "📹 VIDEO" fallback) | Thumbnail generation endpoint |
| 45 | Collection tile "Collection (N images)" with first-image icon and path tooltip | Collection card |
| 46 | Empty/missing media dir messages (currently French) | Empty-state messages (translate) |
| 47 | Clear background/foreground/all (exists in code, not wired) | Optional: add "None" foreground / reset actions (currently no UI) |
| 48 | Window sizing rules (min W+580 x H+200) | Responsive layout; n/a |
| 49 | Resource cleanup on close (timers, generator, thumbnails) | Server: stop preview generators/threads per session (note `cleanup` no-op bug) |
| 50 | Brightness, FPS, metric/collection intervals, font family, date format, custom text, fit mode | **Do not exist** — no equivalent required (only if new features are wanted) |
