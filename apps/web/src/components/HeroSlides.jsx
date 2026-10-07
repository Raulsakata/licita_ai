import { useEffect, useMemo, useState } from 'react';
import { API_URL, useFetch } from '../lib/api';

const SLIDES = 12;

// Fundo rotativo com as mesmas fotos de municípios usadas no mapa interativo.
export default function HeroSlides() {
  const { data } = useFetch('/api/imagens', { tipo: 'cidade' });
  const [index, setIndex] = useState(0);
  const slides = useMemo(() => {
    const all = data || [];
    const tourist = all.filter((img) => (img.credit || '').startsWith('Commons:'));
    const list = [...(tourist.length >= SLIDES ? tourist : all)];
    for (let i = list.length - 1; i > 0; i -= 1) { const j = Math.floor(Math.random() * (i + 1)); [list[i], list[j]] = [list[j], list[i]]; }
    return list.slice(0, SLIDES);
  }, [data]);
  useEffect(() => {
    if (slides.length < 2) return undefined;
    const timer = setInterval(() => setIndex((current) => (current + 1) % slides.length), 6000);
    return () => clearInterval(timer);
  }, [slides.length]);
  if (!slides.length) return null;
  const near = (i) => i === index || i === (index + 1) % slides.length;
  return (
    <div className="hero-slides" aria-hidden="true">
      {slides.map((slide, i) => (
        <div key={slide.key} className={`hero-slide ${i === index ? 'on' : ''}`}
          style={near(i) ? { backgroundImage: `url(${API_URL}/api/imagens/${slide.key})` } : undefined} />
      ))}
      <span className="hero-credit">{slides[index]?.title} · Ceará</span>
    </div>
  );
}
