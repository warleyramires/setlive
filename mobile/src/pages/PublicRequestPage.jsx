import { useEffect, useMemo, useState } from 'react';
import { createPublicAudienceRequest, getPublicSetlist } from '../services/setlistApi';

function extractPublicToken(pathname) {
  const chunks = pathname.split('/').filter(Boolean);
  if (chunks.length < 2 || chunks[0] !== 'public') {
    return '';
  }
  return chunks[1];
}

function PublicRequestPage() {
  const token = useMemo(() => {
    const pathToken = extractPublicToken(window.location.pathname);
    if (pathToken) {
      return pathToken;
    }
    const search = new URLSearchParams(window.location.search);
    return String(search.get('public_token') || search.get('token') || '').trim();
  }, []);
  const [isValidLink, setIsValidLink] = useState(false);
  const [songName, setSongName] = useState('');
  const [requesterName, setRequesterName] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [isPaused, setIsPaused] = useState(false);

  useEffect(() => {
    async function loadSetlist() {
      if (!token) {
        setErrorMessage('Link invalido.');
        setIsLoading(false);
        return;
      }

      setIsLoading(true);
      setErrorMessage('');
      try {
        await getPublicSetlist(token);
        setIsValidLink(true);
      } catch (error) {
        setIsValidLink(false);
        if (error.status === 403) {
          setIsPaused(true);
        } else {
          setErrorMessage(error.message || 'Nao foi possivel carregar o repertorio.');
        }
      } finally {
        setIsLoading(false);
      }
    }

    loadSetlist();
  }, [token]);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!songName.trim()) {
      return;
    }

    setIsSubmitting(true);
    setErrorMessage('');
    setSuccessMessage('');
    try {
      const created = await createPublicAudienceRequest(token, {
        song_name: songName.trim(),
        requester_name: requesterName.trim(),
      });
      setSuccessMessage(`Pedido enviado: ${created.requested_song_name}.`);
      setSongName('');
      setRequesterName('');
    } catch (error) {
      setErrorMessage(error.message || 'Falha ao enviar pedido.');
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="shell">
      <section className="card">
        <h1>Pedido de musica</h1>
        <p>Preencha o formulario e envie sua sugestao para o palco.</p>
        {isLoading ? <p>Carregando pagina...</p> : null}
        {errorMessage ? <p className="error">{errorMessage}</p> : null}
        {isPaused ? (
          <p>O musico pausou os pedidos no momento. Tente novamente mais tarde.</p>
        ) : null}
        {successMessage ? <p className="success">{successMessage}</p> : null}

        {isValidLink ? (
          <form className="form-stack" onSubmit={handleSubmit}>
            <input
              value={requesterName}
              onChange={(event) => setRequesterName(event.target.value)}
              placeholder="Seu nome (opcional)"
              maxLength={80}
            />
            <input
              value={songName}
              onChange={(event) => setSongName(event.target.value)}
              placeholder="Nome da musica"
              maxLength={255}
              required
            />
            <button type="submit" disabled={isSubmitting || !songName.trim()}>
              Enviar pedido
            </button>
          </form>
        ) : null}
      </section>
    </main>
  );
}

export default PublicRequestPage;
