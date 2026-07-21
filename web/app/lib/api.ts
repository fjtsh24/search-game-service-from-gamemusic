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
  game_tags?: { mood_tags: Tag }[];
};

export type Tag = {
  id: string;
  name: string;
  name_ja: string | null;
};

export type Track = {
  id: string;
  title: string;
  track_number: number | null;
  youtube_video_id: string | null;
  track_composers: { is_primary: boolean; composers: { id: string; name: string } }[];
};

export type GameDetail = Game & {
  description: string | null;
  description_ja: string | null;
  description_zh: string | null;
  steam_app_id: number | null;
  game_tags: { tag_id: string; mood_tags: Tag }[];
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

  flagVideo: (gameId: string) =>
    apiFetch<{ flagged: boolean }>(`/games/${gameId}/flag-video`, { method: "POST" }),

  getComposer: (id: string) =>
    apiFetch<Composer>(`/composers/${id}`),

  listTags: () =>
    apiFetch<Tag[]>(`/tags`),

  getTag: (id: string) =>
    apiFetch<Tag>(`/tags/${id}`),
};
