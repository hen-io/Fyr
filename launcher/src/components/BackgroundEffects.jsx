// Renders only the currently active background effect. Previously every
// effect's markup was mounted at once (hidden via CSS for inactive ones) -
// harmless for paint since display:none elements aren't rendered, but every
// App re-render still re-created ~30 child <div> elements and 4 Array.from
// calls for effects nobody could see. Mounting only the active one avoids
// that dead work and keeps this the one place a new effect's DOM shape
// needs to be added.
export function BackgroundEffects({ effect }) {
  switch (effect) {
    case "starfield":
      return <div className="stars-bg" />;

    case "grid":
      return <div className="grid-bg" />;

    case "nebuladrift":
      return (
        <div className="nebula-bg">
          {Array.from({ length: 5 }, (_, i) => (
            <div className="cloud" key={i} />
          ))}
        </div>
      );

    case "prismrays":
      return (
        <div className="prismrays-bg">
          {Array.from({ length: 6 }, (_, i) => (
            <div className="ray" key={i} />
          ))}
        </div>
      );

    case "orbitglow":
      return (
        <div className="orbitglow-bg">
          {Array.from({ length: 5 }, (_, i) => (
            <div className="orbit" key={i}>
              <div className="orbit-dot" />
            </div>
          ))}
        </div>
      );

    case "liquidglass":
      return (
        <div className="rain-bg">
          <div className="beam beam-1" />
          <div className="beam beam-2" />
          <div className="beam beam-3" />
          <div className="beam beam-4" />
          <div className="beam beam-5" />
        </div>
      );

    case "moltenblobs":
      return (
        <div className="lava-bg">
          <div className="lava-blob lava-blob-1" />
          <div className="lava-blob lava-blob-2" />
          <div className="lava-blob lava-blob-3" />
          <div className="lava-blob lava-blob-4" />
          <div className="lava-blob lava-blob-5" />
        </div>
      );

    case "bubblepop":
      return (
        <div className="bubble-bg">
          {Array.from({ length: 10 }, (_, i) => (
            <div className="bubble" key={i} />
          ))}
        </div>
      );

    case "blobs":
    default:
      return (
        <div className="blob-bg">
          <div className="blob blob-1"></div>
          <div className="blob blob-2"></div>
          <div className="blob blob-3"></div>
          <div className="blob blob-4"></div>
          <div className="blob blob-5"></div>
        </div>
      );
  }
}
