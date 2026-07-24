"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Track, authApi } from "@/app/lib/api";

type Props = {
  youtubeVideoId: string | null;
  tracks: Track[];
  gameTitle: string;
  gameId: string;
};

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function totalDurationLabel(tracks: Track[]): string | null {
  const total = tracks.reduce((sum, t) => sum + (t.duration_seconds ?? 0), 0);
  if (total === 0) return null;
  if (total < 3600) return `${Math.floor(total / 60)}分`;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  return `${h}時間${m > 0 ? `${m}分` : ""}`;
}

export default function YouTubePlayer({ youtubeVideoId, tracks, gameTitle, gameId }: Props) {
  const sorted = [...tracks].sort((a, b) => (a.track_number ?? 0) - (b.track_number ?? 0));
  const [flagged, setFlagged] = useState(false);
  const [flagging, setFlagging] = useState(false);
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  useEffect(() => {
    authApi.getMe().then(() => setIsLoggedIn(true)).catch(() => {});
  }, []);

  // YouTube プレーヤー直下に作曲家を表示（全トラックの重複排除）
  const allComposers = sorted
    .flatMap((t) => t.track_composers?.map((tc) => tc.composers) ?? [])
    .filter(Boolean)
    .filter((c, i, arr) => arr.findIndex((x) => x.id === c.id) === i);

  const durLabel = totalDurationLabel(sorted);

  return (
    <section className="flex flex-col gap-4 lg:flex-row lg:items-start">

      {/* 左: YouTube プレーヤー */}
      <div className="flex-1 min-w-0 space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-white/40">
          サウンドトラック
        </h2>

        {youtubeVideoId ? (
          <>
            <div className="aspect-video w-full overflow-hidden rounded-2xl bg-black">
              <iframe
                src={`https://www.youtube.com/embed/${youtubeVideoId}?rel=0`}
                title={`${gameTitle} Soundtrack`}
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
                className="h-full w-full"
              />
            </div>

            <div className="flex flex-wrap items-center gap-3 text-xs">
              {allComposers.length > 0 && (
                <span className="text-white/40">
                  作曲:{" "}
                  {allComposers.map((c, i) => (
                    <span key={c.id}>
                      {i > 0 && " / "}
                      <Link
                        href={`/composers/${c.id}`}
                        className="text-indigo-400 hover:text-indigo-300 hover:underline"
                      >
                        {c.name}
                      </Link>
                    </span>
                  ))}
                </span>
              )}
              <a
                href={`https://www.youtube.com/watch?v=${youtubeVideoId}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-white/25 hover:text-white/50"
              >
                YouTube で開く ↗
              </a>
              {isLoggedIn && (
                flagged ? (
                  <span className="text-white/25">報告済み</span>
                ) : (
                  <button
                    disabled={flagging}
                    onClick={async () => {
                      if (!confirm("この動画が違うと報告しますか？")) return;
                      setFlagging(true);
                      try { await authApi.flagVideo(gameId); setFlagged(true); }
                      catch { /* ignore */ }
                      finally { setFlagging(false); }
                    }}
                    className="text-white/20 hover:text-white/50 disabled:opacity-50"
                  >
                    {flagging ? "報告中..." : "動画が違う場合"}
                  </button>
                )
              )}
            </div>
          </>
        ) : (
          <div className="aspect-video w-full rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center">
            <p className="text-sm text-white/30">動画を準備中です</p>
          </div>
        )}
      </div>

      {/* 右: トラックリスト（固定高さ + スクロール） */}
      {sorted.length > 0 && (
        <div className="lg:w-72 shrink-0 space-y-2">
          <div className="flex items-baseline gap-2">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-white/40">
              トラックリスト
            </h3>
            <span className="text-xs text-white/25">
              {sorted.length}曲{durLabel ? ` · ${durLabel}` : ""}
            </span>
          </div>

          <div className="rounded-xl border border-white/10 bg-white/5 overflow-hidden flex flex-col">
            <ul className="max-h-52 lg:max-h-[420px] overflow-y-auto divide-y divide-white/5">
              {sorted.map((track) => {
                const composerNames = track.track_composers
                  ?.map((tc) => tc.composers?.name)
                  .filter(Boolean) ?? [];

                return (
                  <li
                    key={track.id}
                    className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-white/5 transition"
                  >
                    <span className="w-6 shrink-0 text-right text-xs text-white/20 tabular-nums">
                      {track.track_number ?? "–"}
                    </span>

                    <div className="flex-1 min-w-0">
                      <span className="block text-white/80 line-clamp-1 text-xs leading-tight">
                        {track.title}
                      </span>
                      {composerNames.length > 0 && (
                        <span className="block text-[10px] text-white/30 line-clamp-1">
                          {composerNames.join(" / ")}
                        </span>
                      )}
                    </div>

                    {/* トラック別動画がある場合のみ表示（将来対応、現在は未使用） */}
                    {track.youtube_video_id && (
                      <a
                        href={`https://www.youtube.com/watch?v=${track.youtube_video_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        title="この曲の動画を YouTube で見る"
                        className="shrink-0 rounded px-1 py-0.5 text-[10px] bg-red-900/40 text-red-400 hover:bg-red-800/60 transition"
                      >
                        ▶
                      </a>
                    )}

                    {track.duration_seconds != null && (
                      <span className="shrink-0 text-[10px] text-white/20 tabular-nums">
                        {formatDuration(track.duration_seconds)}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
            {durLabel && (
              <div className="border-t border-white/5 px-3 py-1.5 text-right text-[10px] text-white/20 shrink-0">
                合計 {durLabel}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
