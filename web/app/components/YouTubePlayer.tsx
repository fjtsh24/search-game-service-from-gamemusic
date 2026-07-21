"use client";

import { useState } from "react";
import Link from "next/link";
import { Track } from "@/app/lib/api";

type Props = {
  tracks: Track[];
  gameTitle: string;
};

export default function YouTubePlayer({ tracks, gameTitle }: Props) {
  const playable = tracks.filter((t) => t.youtube_video_id);
  const [activeIndex, setActiveIndex] = useState(0);

  if (playable.length === 0) {
    return (
      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-white/40">
          サウンドトラック
        </h2>
        <div className="aspect-video w-full max-w-2xl rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center">
          <p className="text-sm text-white/30">動画を準備中です</p>
        </div>
      </section>
    );
  }

  const active = playable[activeIndex];
  const composers = active.track_composers
    ?.map((tc) => tc.composers)
    .filter(Boolean)
    .filter((c, i, arr) => arr.findIndex((x) => x.id === c.id) === i) ?? [];

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-white/40">
        サウンドトラック
      </h2>

      <div className="flex flex-col gap-4 lg:flex-row">
        {/* プレーヤー */}
        <div className="flex-1 space-y-3">
          <div className="aspect-video w-full overflow-hidden rounded-2xl bg-black">
            <iframe
              key={active.youtube_video_id}
              src={`https://www.youtube.com/embed/${active.youtube_video_id}?rel=0`}
              title={active.title ?? gameTitle}
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
              allowFullScreen
              className="h-full w-full"
            />
          </div>

          {/* アクティブトラックの情報 */}
          <div className="rounded-xl border border-white/10 bg-white/5 px-4 py-3 space-y-1">
            {active.track_number && (
              <p className="text-xs text-white/30">Track {active.track_number}</p>
            )}
            <p className="font-medium text-white">{active.title ?? gameTitle}</p>
            {composers.length > 0 && (
              <p className="text-sm text-white/50">
                作曲:{" "}
                {composers.map((c, i) => (
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
              </p>
            )}
            <div className="flex items-center gap-3">
              <a
                href={`https://www.youtube.com/watch?v=${active.youtube_video_id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-block text-xs text-white/30 hover:text-white/60"
              >
                YouTube で開く ↗
              </a>
              <a
                href={`https://github.com/fjtsh24/search-game-service-from-gamemusic/issues/new?title=動画が違う: ${encodeURIComponent(gameTitle)}&body=${encodeURIComponent(`ゲーム: ${gameTitle}\n動画ID: ${active.youtube_video_id}\n\n正しい動画のURLや動画名を教えてください。`)}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-block text-xs text-white/20 hover:text-white/50"
              >
                動画が違う場合 ↗
              </a>
            </div>
          </div>
        </div>

        {/* トラックリスト（複数ある場合のみ表示） */}
        {playable.length > 1 && (
          <div className="w-full lg:w-64 shrink-0">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-white/30">
              トラック一覧 ({playable.length})
            </p>
            <ul className="space-y-1 max-h-80 overflow-y-auto">
              {playable.map((track, i) => {
                const isActive = i === activeIndex;
                return (
                  <li key={track.id}>
                    <button
                      onClick={() => setActiveIndex(i)}
                      className={`w-full rounded-lg px-3 py-2 text-left text-sm transition ${
                        isActive
                          ? "bg-indigo-600 text-white"
                          : "text-white/60 hover:bg-white/10 hover:text-white"
                      }`}
                    >
                      <span className="mr-2 text-xs opacity-50">
                        {track.track_number ?? i + 1}.
                      </span>
                      <span className="line-clamp-1">{track.title}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}
