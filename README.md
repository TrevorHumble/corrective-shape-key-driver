# Corrective Shape Key Drivers

**Version 1.5.2** | Blender 4.5+

A Blender addon that creates corrective shape key drivers from evaluated bone positions. Works with IK, FK, and constraints — and includes bake-to-keyframes for game engine export.

![Sidebar panel](docs/screenshot.png)
<!-- Replace with an actual screenshot of the View3D sidebar panel -->

---

## Features

- Drive any shape key from a bone's normalized position along X, Y, or Z
- IK-friendly: reads evaluated (post-constraint) bone position, not rest pose
- 2-point linear, 3-point quadratic, or 4+ piecewise-linear curve fitting
- Capture and recapture control points live from the current pose
- **Auto-prepare shape keys from bone name** — one click creates Basis + bone-named key + mirrored variant, no manual setup needed
- Mirror driver to the opposite side (`.l` ↔ `.r`) in one click — automatically creates and names the mirrored shape key if needed, and mirrors vertex offsets
- Bake all driven shape keys to per-frame keyframes for Unity / Unreal / Godot export

---

## Compatibility

| Blender | Status |
|---------|--------|
| 4.5+    | Supported |
| 4.0–4.4 | Untested |
| 3.x     | Not supported |

Works on Windows, macOS, and Linux.

---

## Installation

1. Download the latest `.zip` from the [Releases](https://github.com/TrevorHumble/corrective-shape-key-driver/releases) page — do **not** unzip it.
2. Open Blender and go to **Edit > Preferences > Add-ons**.
3. Click **Install…** in the top-right corner.
4. Navigate to the downloaded `.zip` and click **Install Add-on**.
5. Check the box next to **Rigging: Corrective Shape Key Drivers** to enable it.
6. In the same Preferences window, go to **Save & Load** and enable **Auto Run Python Scripts** — the addon requires this to evaluate drivers.

The panel appears in the **3D Viewport sidebar** (press `N`) under the **Corrective SK** tab.

---

## Usage

### Basic workflow

1. **Select your armature** and pick the **bone** whose movement should drive the shape key.
2. **Select your mesh.** If a shape key matching the bone doesn't exist yet, the Shape Key row shows a **Prepare** button — click it to create a Basis key, a shape key named after the bone, and a mirrored variant if the bone uses `.l` / `.r` naming.
3. **Choose an axis** (X / Y / Z) to track.
4. **Pose the bone** to a position where the shape key should be fully on, then click **Capture** and set the strength to `1.0`.
5. **Pose the bone** to a neutral position (shape key off), click **Capture** again with strength `0.0`.
6. Click **Generate Driver**. The shape key is now driven.

Add more control points between neutral and full-on for a smoother curve.

### Mirroring

Click **Mirror to Other Side** to duplicate the driver setup to the opposite side. The operator automatically creates the mirrored shape key (from Basis) if it doesn't exist, renames unsuffixed shape keys by inferring the side from the bone name, and mirrors the vertex offsets across X. The bone must use `.l` / `.r` (or `.L` / `.R`, `_l` / `_r`, `.left` / `.right`) naming.

### Game engine export

1. Click **Bake to Keyframes** and set your frame range.
2. The addon evaluates the driver at every frame and writes keyframes.
3. Drivers are removed after baking so the file exports cleanly to Unity, Unreal, or Godot.

---

## Known Limitations

- **Auto Run Python Scripts must be enabled** — Blender blocks driver expressions otherwise. You'll see a warning in the panel if it's off.
- **The mesh must have shape keys to generate a driver** — use the **Prepare Shape Keys** button to create them automatically, or add them manually in Properties > Object Data. The Shape Key dropdown and Generate Driver button only activate once a Basis key and at least one corrective key exist.
- **Mirror requires the bone to have a side suffix** — the bone name must end in `.l` / `.r` (or `.L` / `.R`, `_l` / `_r`, `.left` / `.right`) so the addon knows which mirrored bone to target. The shape key does not need a suffix — the addon will rename it automatically.

---

## License

GPL v3 — see [LICENSE](LICENSE).
