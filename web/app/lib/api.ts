const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type User = {
  id: string;
  steam_id: string;
  display_name: string | null;
  avatar_url: string | null;
};

export type UserGame = {
  id: string;
  game_id: string;
  rating: number | null;
  steam_playtime_minutes: number | null;
  added_at: string;
  games: Game;
};

export type LibraryImportResult = {
  imported: number;
  matched: number;
};

export type Game = {
  id: string;
  title: string;
  title_ja: string | null;
  release_year: number | null;
  cover_image_url: string | null;
  game_tags?: { confidence?: number | null; mood_tags: Tag }[];
  reason_tags?: Tag[];
};

export type Tag = {
  id: string;
  name: string;
  name_ja: string | null;
};

/**
 * タグ 1 件と、その付与根拠の強さ（confidence）。
 *
 * confidence は付与ソースごとの証拠の強さを表す
 * （docs/planning/08_tagging_redesign.md §6-A）:
 *   0.9 前後 = 音楽そのものの記述に基づく直接証拠（Last.fm / Steam OST 説明文）
 *   0.5 未満 = ゲームの雰囲気からの推定
 * 推定タグは UI 上で「推定」と明示する。
 */
export type ScoredTag = Tag & { confidence?: number | null };

/** これ未満の confidence を「推定タグ」として区別表示する閾値。 */
export const ESTIMATED_TAG_THRESHOLD = 0.7;

export function isEstimatedTag(tag: { confidence?: number | null }): boolean {
  return tag.confidence != null && tag.confidence < ESTIMATED_TAG_THRESHOLD;
}

export type Track = {
  id: string;
  title: string;
  track_number: number | null;
  duration_seconds: number | null;
  youtube_video_id: string | null;
  track_composers: { is_primary: boolean; composers: { id: string; name: string } }[];
};

export type GameDetail = Game & {
  description: string | null;
  description_ja: string | null;
  description_zh: string | null;
  steam_app_id: number | null;
  youtube_video_id: string | null;
  youtube_flagged: boolean;
  game_tags: { tag_id: string; confidence: number | null; mood_tags: Tag }[];
  tracks: Track[];
};

export type Composer = {
  id: string;
  name: string;
  bio: string | null;
  image_url: string | null;
  games: Game[];
};

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API error: ${res.status} ${path}`);
  return res.json();
}

// クライアント側から認証 Cookie を送る必要がある API 呼び出し用
async function authFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!res.ok) throw new Error(`API error: ${res.status} ${path}`);
  return res.json();
}

export const authApi = {
  getMe: () => authFetch<User>("/users/me"),
  logout: () =>
    fetch(`${API_URL}/auth/logout`, { method: "POST", credentials: "include" }),
  deleteAccount: () =>
    fetch(`${API_URL}/auth/account`, { method: "DELETE", credentials: "include" }),
  importLibrary: () =>
    authFetch<LibraryImportResult>("/users/me/library/import", { method: "POST" }),
  getLibrary: () => authFetch<UserGame[]>("/users/me/library"),
  getFeed: () => authFetch<Game[]>("/users/me/feed"),
  rateGame: (gameId: string, rating: number) =>
    authFetch<{ ok: boolean }>(`/users/me/games/${gameId}/rating`, {
      method: "POST",
      body: JSON.stringify({ rating }),
    }),

  flagVideo: (gameId: string) =>
    authFetch<{ flagged: boolean }>(`/games/${gameId}/flag-video`, { method: "POST" }),

  flagTag: (gameId: string, tagId: string) =>
    authFetch<{ flagged: boolean }>(`/games/${gameId}/flag-tag`, {
      method: "POST",
      body: JSON.stringify({ tag_id: tagId }),
    }),
};

export const api = {
  searchGames: (q: string) =>
    apiFetch<Game[]>(`/search/games?q=${encodeURIComponent(q)}`),

  searchComposers: (q: string) =>
    apiFetch<Composer[]>(`/search/composers?q=${encodeURIComponent(q)}`),

  listGames: (tagId?: string, limit = 20, random = false) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (tagId) params.set("tag_id", tagId);
    if (random) params.set("random", "true");
    return apiFetch<Game[]>(`/games?${params}`);
  },

  getGame: (id: string) =>
    apiFetch<GameDetail>(`/games/${id}`),

  getSimilarGames: (id: string) =>
    apiFetch<Game[]>(`/games/${id}/similar`),

  getComposer: (id: string) =>
    apiFetch<Composer>(`/composers/${id}`),

  listTags: () =>
    apiFetch<Tag[]>(`/tags`),

  getTag: (id: string) =>
    apiFetch<Tag>(`/tags/${id}`),
};
