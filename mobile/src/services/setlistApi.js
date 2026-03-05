import { REPERTOIRE_API_BASE_URL } from '../config/api';
import { readTokens } from './tokenStorage';

const audienceQueueCacheBySetlist = new Map();
const audienceQueueEtagBySetlist = new Map();

function authHeaders() {
  const tokens = readTokens();
  return {
    Authorization: `Bearer ${tokens?.access ?? ''}`,
    'Content-Type': 'application/json',
  };
}

async function parseError(response, fallback) {
  try {
    const body = await response.json();
    if (body?.detail) {
      return body.detail;
    }

    if (typeof body === 'object' && body !== null) {
      const firstField = Object.keys(body)[0];
      const firstValue = body[firstField];
      if (Array.isArray(firstValue) && firstValue.length > 0) {
        return String(firstValue[0]);
      }
      if (typeof firstValue === 'string') {
        return firstValue;
      }
    }
  } catch {
    // no-op
  }

  return fallback;
}

async function requestJson(url, options = {}, fallbackError = 'Erro na requisicao.') {
  const response = await fetch(url, {
    ...options,
    headers: {
      ...authHeaders(),
      ...(options.headers ?? {}),
    },
  });

  if (!response.ok) {
    throw new Error(await parseError(response, fallbackError));
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

async function requestPublicJson(url, options = {}, fallbackError = 'Erro na requisicao publica.') {
  const response = await fetch(url, options);

  if (!response.ok) {
    throw new Error(await parseError(response, fallbackError));
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

export async function listSongs({ search = '', page = 1, pageSize = 30 } = {}) {
  const params = new URLSearchParams();
  if (search.trim()) {
    params.set('search', search.trim());
  }
  params.set('page', String(page));
  params.set('page_size', String(pageSize));

  const payload = await requestJson(
    `${REPERTOIRE_API_BASE_URL}/songs/?${params.toString()}`,
    {},
    'Falha ao listar musicas.'
  );

  if (Array.isArray(payload)) {
    return {
      items: payload,
      page: 1,
      page_size: payload.length,
      total: payload.length,
      has_previous: false,
      has_next: false,
    };
  }

  return payload;
}

export function createSong({ title, artist }) {
  return requestJson(
    `${REPERTOIRE_API_BASE_URL}/songs/`,
    {
      method: 'POST',
      body: JSON.stringify({ title, artist }),
    },
    'Falha ao criar musica.'
  );
}

export function updateSong(songId, payload) {
  return requestJson(
    `${REPERTOIRE_API_BASE_URL}/songs/${songId}/`,
    {
      method: 'PATCH',
      body: JSON.stringify(payload),
    },
    'Falha ao atualizar musica.'
  );
}

export function listSetlists() {
  return requestJson(`${REPERTOIRE_API_BASE_URL}/setlists/`, {}, 'Falha ao listar repertorios.');
}

export function createSetlist({ name }) {
  return requestJson(
    `${REPERTOIRE_API_BASE_URL}/setlists/`,
    {
      method: 'POST',
      body: JSON.stringify({ name }),
    },
    'Falha ao criar repertorio.'
  );
}

export function getSetlist(setlistId) {
  return requestJson(`${REPERTOIRE_API_BASE_URL}/setlists/${setlistId}/`, {}, 'Falha ao carregar repertorio.');
}

export function updateSetlist(setlistId, { name }) {
  return requestJson(
    `${REPERTOIRE_API_BASE_URL}/setlists/${setlistId}/`,
    {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    },
    'Falha ao atualizar repertorio.'
  );
}

export function deleteSetlist(setlistId) {
  return requestJson(
    `${REPERTOIRE_API_BASE_URL}/setlists/${setlistId}/`,
    {
      method: 'DELETE',
    },
    'Falha ao remover repertorio.'
  );
}

export function addSetlistItem(setlistId, songId) {
  return requestJson(
    `${REPERTOIRE_API_BASE_URL}/setlists/${setlistId}/items/`,
    {
      method: 'POST',
      body: JSON.stringify({ song_id: songId }),
    },
    'Falha ao adicionar musica ao repertorio.'
  );
}

export function reorderSetlist(setlistId, itemIds) {
  return requestJson(
    `${REPERTOIRE_API_BASE_URL}/setlists/${setlistId}/reorder/`,
    {
      method: 'POST',
      body: JSON.stringify({ item_ids: itemIds }),
    },
    'Falha ao reordenar repertorio.'
  );
}

export function deleteSetlistItem(itemId) {
  return requestJson(
    `${REPERTOIRE_API_BASE_URL}/items/${itemId}/`,
    {
      method: 'DELETE',
    },
    'Falha ao remover item do repertorio.'
  );
}

export function fetchSongCifra(songId) {
  return requestJson(
    `${REPERTOIRE_API_BASE_URL}/songs/${songId}/cifra/`,
    {},
    'Falha ao buscar cifra.'
  );
}

export function getSetlistAudienceLink(setlistId) {
  return requestJson(
    `${REPERTOIRE_API_BASE_URL}/setlists/${setlistId}/audience-link/`,
    {},
    'Falha ao gerar link publico.'
  );
}

export function listSetlistAudienceRequests(setlistId) {
  const cacheKey = String(setlistId);
  const previousEtag = audienceQueueEtagBySetlist.get(cacheKey);
  const url = `${REPERTOIRE_API_BASE_URL}/setlists/${setlistId}/requests/`;

  return fetch(url, {
    headers: {
      ...authHeaders(),
      ...(previousEtag ? { 'If-None-Match': previousEtag } : {}),
    },
  }).then(async (response) => {
    if (response.status === 304) {
      const cached = audienceQueueCacheBySetlist.get(cacheKey);
      if (cached) {
        return cached;
      }
      const fullResponse = await fetch(url, {
        headers: {
          ...authHeaders(),
        },
      });
      if (!fullResponse.ok) {
        throw new Error(await parseError(fullResponse, 'Falha ao carregar fila de pedidos.'));
      }
      const fullPayload = await fullResponse.json();
      const fullEtag = fullResponse.headers.get('ETag');
      if (fullEtag) {
        audienceQueueEtagBySetlist.set(cacheKey, fullEtag);
      }
      audienceQueueCacheBySetlist.set(cacheKey, fullPayload);
      return fullPayload;
    }

    if (!response.ok) {
      throw new Error(await parseError(response, 'Falha ao carregar fila de pedidos.'));
    }

    const payload = response.status === 204 ? null : await response.json();
    const nextEtag = response.headers.get('ETag');
    if (nextEtag) {
      audienceQueueEtagBySetlist.set(cacheKey, nextEtag);
    }
    if (payload) {
      audienceQueueCacheBySetlist.set(cacheKey, payload);
    }
    return payload;
  });
}

export function getPublicSetlist(token) {
  return requestPublicJson(
    `${REPERTOIRE_API_BASE_URL}/public/setlists/${token}/`,
    {},
    'Falha ao carregar repertorio publico.'
  );
}

export function createPublicAudienceRequest(token, payload) {
  return requestPublicJson(
    `${REPERTOIRE_API_BASE_URL}/public/setlists/${token}/requests/`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    },
    'Falha ao enviar pedido.'
  );
}
