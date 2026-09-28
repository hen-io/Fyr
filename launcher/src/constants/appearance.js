// Single source of truth for every selectable palette/background/hover
// effect. Adding a new one is a one-place edit here - SettingsWindow's
// <select> options and BackgroundEffects' rendering both read from this
// file instead of hardcoding their own copies.

export const PALETTES = [
  { value: "amber", label: "Amber & Gold" },
  { value: "hyperblue", label: "Blue & Teal" },
  { value: "crimson", label: "Crimson & Orange" },
  { value: "cybercyan", label: "Cyan, Yellow & Magenta" },
  { value: "deepspace", label: "Deep Space Navy" },
  { value: "emerald", label: "Emerald & Violet" },
  { value: "acidgreen", label: "Green & Amber" },
  { value: "vaporwave", label: "Hot Pink & Blue" },
  { value: "icysilver", label: "Icy Silver" },
  { value: "lavared", label: "Lava Red" },
  { value: "aurora", label: "Mint & Blue" },
  { value: "ocean", label: "Ocean Blue" },
  { value: "moltenheat", label: "Orange, Red & Violet" },
  { value: "candypop", label: "Pink & Cyan" },
  { value: "bubblegum", label: "Pink, Cyan & Yellow" },
  { value: "neonpink", label: "Pink, Violet & Cyan" },
  { value: "royalgold", label: "Royal Gold" },
  { value: "sunset", label: "Sunset Orange" },
  { value: "toxiclime", label: "Toxic Lime" },
  { value: "violet", label: "Violet & Magenta" },
];

export const BACKGROUND_EFFECTS = [
  { value: "blobs", label: "Blobs" },
  { value: "bubblepop", label: "Bubble Pop" },
  { value: "grid", label: "Grid" },
  { value: "liquidglass", label: "Liquid Glass" },
  { value: "moltenblobs", label: "Molten Blobs" },
  { value: "orbitglow", label: "Orbit Glow" },
  { value: "prismrays", label: "Prism Rays" },
  { value: "nebuladrift", label: "Nebula Drift" },
  { value: "starfield", label: "Starfield" },
];

export const HOVER_EFFECTS = [
  { value: "tilt3d", label: "3D Tilt" },
  { value: "glow", label: "Neon Glow" },
  { value: "lift", label: "Lift & Shadow" },
  { value: "shine", label: "Shine Sweep" },
];
