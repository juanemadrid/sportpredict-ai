import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SPORTPREDICT AI | Plataforma SaaS de Análisis y Predicción Deportiva con ML",
  description:
    "Motor estadístico y de Machine Learning (Poisson, Elo, Random Forest, XGBoost y Ensamble) con validación temporal estricta y análisis de valor esperado (EV).",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es">
      <body className="min-h-screen bg-slate-50 text-slate-900">{children}</body>
    </html>
  );
}
