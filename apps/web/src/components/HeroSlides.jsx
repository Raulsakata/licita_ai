import { useEffect, useState } from 'react';
import { API_URL, useFetch } from '../lib/api';

// Pontos turísticos do Ceará (imagens gravadas no banco) como fundo rotativo do cabeçalho.
export default function HeroSlides() {
  const { data } = useFetch('/api/imagens', { tipo: 'turismo' });
  const [index, setIndex] = useState(0);
  const slides = data || [];
  useEffect(() => {
    if (slides.length < 2) return undefined;
    const timer = setInterval(() => setIndex((current) => (current + 1) % slides.length), 6000);
    return () => clearInterval(timer);
  }, [slides.length]);
  if (!slides.length) return null;
  return (
    <div className="hero-slides" aria-hidden="true">
      {slides.map((slide, i) => (
        <div key={slide.key} className={`hero-slide ${i === index ? 'on' : ''}`}
          style={i === index || i === (index + 1) % slides.length ? { backgroundImage: `url(${API_URL}/api/imagens/${slide.key})` } : undefined} />
      ))}
      <span className="hero-credit">{slides[index]?.title}</span>
    </div>
  );
}
