import { memo } from "react";
import { Tile } from "./Tile.jsx";
import { CATEGORY_ICONS } from "../constants/categories.js";
import Icon from "@mdi/react";

// Memoized: with useWindowManager's callbacks now stable (useCallback) and
// appPrefs only changing reference when it's actually updated, every prop
// here is stable unless something meaningful changed - so this can safely
// skip re-rendering (and re-rendering all ~18 tiles) when unrelated App
// state changes (e.g. the settings dropdown opening/closing).
export const TileGrid = memo(function TileGrid({
  apps,
  tilesPerRow,
  hoverEffect,
  openInWindow,
  appPrefs,
  onOpenApp,
  statusInterval,
  disabled,
  isAuthenticated,
  layout,
}) {
  // A tile can set visibility: "authenticated" to stay hidden from
  // anonymous visitors (any logged-in user - visitor or admin role - can
  // still see it; the split here is "logged in at all" vs "not").
  const visible = apps.filter((tile) => !tile.visibility || tile.visibility !== "authenticated" || isAuthenticated);

  // Group tiles by category (including uncategorized) - used unless a
  // custom layout (backend-data/ui.conf) is active, see below.
  const categories = visible.reduce(
    (acc, tile) => {
      const key = tile.category || "_no_category";
      if (!acc[key]) {
        acc[key] = { items: [], name: tile.category || null, icon: (tile.category && CATEGORY_ICONS[tile.category]) || null };
      }
      acc[key].items.push(tile);
      return acc;
    },
    { _no_category: { items: [], name: null, icon: null } }
  );
  const ordered = Object.entries(categories); // KEEP ORIGINAL ORDER — NO SORTING

  const isAutoRow = tilesPerRow === "auto";
  const hasCustomLayout = layout && Object.keys(layout).length > 0;

  // Dynamic tile width for large screens, clamped so a single-column grid
  // doesn't blow up to the full viewport width. Unused in auto-row mode.
  const tileWidth = isAutoRow ? null : `min(calc((100% - ${(tilesPerRow - 1) * 48}px) / ${tilesPerRow}), 33vw)`;

  const renderTile = (app) => (
    <Tile
      key={app.title}
      {...app}
      hoverEffect={hoverEffect}
      openInWindow={openInWindow}
      appPrefs={appPrefs}
      onOpenApp={onOpenApp}
      statusInterval={statusInterval}
    />
  );

  return (
    <div
      style={{
        width: "100%",
        display: "flex",
        justifyContent: "center",
        pointerEvents: disabled ? "none" : "auto",
        opacity: disabled ? 0.35 : 1,
        transition: "opacity 0.3s ease",
      }}
    >
      <div
        style={{
          width: "min(90%, 1400px)",
          padding: "20px",
          boxSizing: "border-box",
        }}
      >
        <style>
          {`
            /* Autoscale on narrow screens */
            @media (max-width: 900px) {
              .auto-grid {
                grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)) !important;
              }
            }
          `}
        </style>

        {hasCustomLayout ? (
          // Custom layout (backend-data/ui.conf) - one flat grid, explicit
          // positions where configured; any tile without an entry is left
          // to the browser's normal auto-placement in the same grid.
          // Category grouping doesn't apply here - positioning is
          // admin-driven instead of category-driven.
          <div
            className="auto-grid"
            style={{
              display: "grid",
              gridTemplateColumns: `repeat(${isAutoRow ? 6 : tilesPerRow}, ${tileWidth || "140px"})`,
              gridAutoRows: "140px",
              justifyContent: "center",
              gap: "48px",
            }}
          >
            {visible.map((app) => {
              const pos = layout[app.title];
              const style = pos ? { gridColumn: `${pos.x + 1} / span ${pos.w}`, gridRow: `${pos.y + 1} / span ${pos.h}` } : undefined;
              return (
                <div key={app.title} style={style}>
                  {renderTile(app)}
                </div>
              );
            })}
          </div>
        ) : (
          ordered.map(([key, data]) => {
            if (data.items.length === 0) return null;

            const isNoCategory = key === "_no_category";

            return (
              <div key={key} style={{ marginBottom: "50px" }}>
                {/* CATEGORY HEADER — HIDDEN FOR NO-CATEGORY */}
                {!isNoCategory && (
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "12px",
                      marginBottom: "20px",
                    }}
                  >
                    {data.icon && <Icon path={data.icon} size={1.2} />}

                    <span
                      style={{
                        fontSize: "1.6rem",
                        fontWeight: "600",
                        opacity: 0.9,
                        whiteSpace: "nowrap",
                      }}
                    >
                      {data.name}
                    </span>

                    {/* SEPARATOR WITH SHADOW */}
                    <div
                      className="category-separator"
                      style={{
                        flexGrow: 1,
                        height: "5px",
                        background: "rgba(255,255,255,0.22)",
                        borderRadius: "6px",
                        marginLeft: "14px",
                      }}
                    />
                  </div>
                )}

                {/* TILE GRID */}
                {isAutoRow ? (
                  <div style={{ display: "flex", gap: "48px", overflowX: "auto", paddingBottom: 8 }}>
                    {data.items.map((app) => (
                      <div key={app.title} style={{ flex: "0 0 160px", width: 160 }}>
                        {renderTile(app)}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div
                    className="auto-grid"
                    style={{
                      display: "grid",
                      gridTemplateColumns: `repeat(${tilesPerRow}, ${tileWidth})`,
                      justifyContent: "center",
                      gap: "48px",
                    }}
                  >
                    {data.items.map((app) => renderTile(app))}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
});
