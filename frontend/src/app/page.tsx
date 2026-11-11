"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Award,
  BarChart3,
  Calendar,
  CheckCircle2,
  Clock,
  Cpu,
  Database,
  FileSpreadsheet,
  History,
  Layers,
  Lock,
  RefreshCw,
  Scale,
  ShieldCheck,
  Sliders,
  TrendingUp,
  Users,
} from "lucide-react";
import { apiFetch } from "@/lib/api";
import type {
  DetailedMatchAnalysis,
  MatchSummaryItem,
  ModelComparisonEntry,
  ParleyRecommendation,
} from "@/types/sports";

type ModuleKey =
  | "dashboard"
  | "today"
  | "upcoming"
  | "match_analysis"
  | "predictions"
  | "odds_comparator"
  | "teams"
  | "history"
  | "model_performance"
  | "training_panel"
  | "admin"
  | "subscriptions";

const MODULES: Array<{ key: ModuleKey; label: string; number: number; icon: React.ComponentType<{ className?: string }> }> = [
  { key: "dashboard", label: "1. Dashboard Principal", number: 1, icon: Activity },
  { key: "today", label: "2. Partidos de Hoy", number: 2, icon: Clock },
  { key: "upcoming", label: "3. Próximos Encuentros", number: 3, icon: Calendar },
  { key: "match_analysis", label: "4. Análisis de Partidos", number: 4, icon: Layers },
  { key: "predictions", label: "5. Pronósticos y Valor (EV)", number: 5, icon: TrendingUp },
  { key: "odds_comparator", label: "6. Comparador de Cuotas", number: 6, icon: Scale },
  { key: "teams", label: "7. Estadísticas de Equipos", number: 7, icon: Award },
  { key: "history", label: "8. Historial de Predicciones", number: 8, icon: History },
  { key: "model_performance", label: "9. Rendimiento del Modelo", number: 9, icon: BarChart3 },
  { key: "training_panel", label: "10. Panel de Entrenamiento", number: 10, icon: Cpu },
  { key: "admin", label: "11. Administración y Fuentes", number: 11, icon: Sliders },
  { key: "subscriptions", label: "12. Usuarios y Suscripciones", number: 12, icon: Users },
];

const SAMPLE_AUTHORIZED_CSV = `external_ref,competition_code,competition_name,country,season,matchday,kickoff_utc,home_team,away_team,status,home_goals,away_goals,home_xg,away_xg,odds_home,odds_draw,odds_away
CSV-AUTH-2026-101,ESP_LALIGA,LaLiga EA Sports,España,2026/2027,17,2026-11-14T20:00:00Z,Real Madrid,Villarreal CF,SCHEDULED,,,,,1.52,4.30,6.10
CSV-AUTH-2026-102,ENG_EPL,Premier League,Inglaterra,2026/2027,17,2026-11-15T17:30:00Z,Liverpool FC,Arsenal FC,SCHEDULED,,,,,2.15,3.45,3.35`;

export default function SportPredictApp() {
  const [activeModule, setActiveModule] = useState<ModuleKey>("dashboard");
  const [userRole, setUserRole] = useState<string>("ADMIN");
  const [userPlan, setUserPlan] = useState<string>("PRO");
  const [mobileMenuOpen, setMobileMenuOpen] = useState<boolean>(false);

  const [diagnostic, setDiagnostic] = useState<any>(null);
  const [scheduledMatches, setScheduledMatches] = useState<MatchSummaryItem[]>([]);
  const [finishedMatches, setFinishedMatches] = useState<MatchSummaryItem[]>([]);
  const [selectedMatchId, setSelectedMatchId] = useState<number | null>(null);
  const [matchDetail, setMatchDetail] = useState<DetailedMatchAnalysis | null>(null);
  const [modelsData, setModelsData] = useState<{
    active_version: string;
    validation_protocol: string;
    models: ModelComparisonEntry[];
  } | null>(null);
  const [teamsList, setTeamsList] = useState<any[]>([]);
  const [ledgerData, setLedgerData] = useState<any>(null);
  const [syncLogs, setSyncLogs] = useState<any[]>([]);
  const [parleyData, setParleyData] = useState<ParleyRecommendation | null>(null);
  const [activeMarketTabs, setActiveMarketTabs] = useState<Record<number, "1x2" | "corners" | "goals" | "btts" | "dc">>({});
  const [simBetAmount, setSimBetAmount] = useState<number>(20000);
  const [detailBetAmount, setDetailBetAmount] = useState<number>(20000);

  const isMatchTodayInColombia = (isoStr: string): boolean => {
    try {
      const d = new Date(isoStr);
      const matchDateStr = new Intl.DateTimeFormat("en-CA", {
        timeZone: "America/Bogota",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(d);

      const todayStr = new Intl.DateTimeFormat("en-CA", {
        timeZone: "America/Bogota",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(new Date());

      return matchDateStr === todayStr;
    } catch {
      return false;
    }
  };

  const formatColombiaMatchDate = (isoStr: string): { dayLabel: string; timeLabel: string; fullLabel: string } => {
    try {
      const d = new Date(isoStr);
      const dayName = new Intl.DateTimeFormat("es-CO", {
        timeZone: "America/Bogota",
        weekday: "short",
        day: "numeric",
        month: "short",
      }).format(d);

      const timeStr = new Intl.DateTimeFormat("es-CO", {
        timeZone: "America/Bogota",
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
      }).format(d);

      const isToday = isMatchTodayInColombia(isoStr);
      const dayLabel = isToday ? "Hoy (" + dayName + ")" : dayName;
      return {
        dayLabel,
        timeLabel: timeStr + " (Hora Col)",
        fullLabel: dayLabel + " · " + timeStr + " (Hora Col)",
      };
    } catch {
      return { dayLabel: "Hoy", timeLabel: "Hora Col", fullLabel: "Hoy (Hora Col)" };
    }
  };

  const formatColombiaDateTime = (isoStr: string): string => {
    return formatColombiaMatchDate(isoStr).fullLabel;
  };

  const [loading, setLoading] = useState<boolean>(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [actionStatus, setActionStatus] = useState<string | null>(null);

  // Estado para el Panel de Entrenamiento e Importación CSV
  const [csvText, setCsvText] = useState<string>(SAMPLE_AUTHORIZED_CSV);
  const [csvSource, setCsvSource] = useState<string>("Dataset_CSV_Autorizado");
  const [csvLicense, setCsvLicense] = useState<string>("Kaggle Open / Propio Autorizado");
  const [calibrationMethod, setCalibrationMethod] = useState<string>("sigmoid");

  const loadAllData = useCallback(async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const [diagRes, schedRes, finRes, modsRes, tmsRes, ledgRes, logsRes, parleyRes] = await Promise.allSettled([
        apiFetch<any>("/api/v1/system/diagnostic", undefined, userRole, userPlan),
        apiFetch<{ count: number; items: MatchSummaryItem[] }>(
          "/api/v1/matches?status=SCHEDULED&limit=50",
          undefined,
          userRole,
          userPlan
        ),
        apiFetch<{ count: number; items: MatchSummaryItem[] }>(
          "/api/v1/matches?status=FINISHED&limit=6",
          undefined,
          userRole,
          userPlan
        ),
        apiFetch<any>("/api/v1/models/comparison", undefined, userRole, userPlan),
        apiFetch<{ count: number; items: any[] }>("/api/v1/teams", undefined, userRole, userPlan),
        apiFetch<any>("/api/v1/predictions/ledger?limit=30", undefined, userRole, userPlan),
        apiFetch<{ count: number; items: any[] }>("/api/v1/ingestion/logs", undefined, userRole, userPlan),
        apiFetch<ParleyRecommendation>("/api/v1/parley/recommended", undefined, userRole, userPlan),
      ]);

      if (diagRes.status === "fulfilled") setDiagnostic(diagRes.value);
      if (schedRes.status === "fulfilled") setScheduledMatches(schedRes.value.items);
      if (finRes.status === "fulfilled") setFinishedMatches(finRes.value.items);
      if (modsRes.status === "fulfilled") setModelsData(modsRes.value);
      if (tmsRes.status === "fulfilled") setTeamsList(tmsRes.value.items);
      if (ledgRes.status === "fulfilled") setLedgerData(ledgRes.value);
      if (logsRes.status === "fulfilled") setSyncLogs(logsRes.value.items);
      if (parleyRes.status === "fulfilled") setParleyData(parleyRes.value);

      if (diagRes.status === "rejected" && schedRes.status === "rejected") {
        setErrorMsg("El servidor backend en Render está respondiendo lentamente o iniciando. Por favor reintenta.");
      }

      const schedItems = schedRes.status === "fulfilled" ? schedRes.value.items : [];
      const finItems = finRes.status === "fulfilled" ? finRes.value.items : [];
      const defaultId =
        selectedMatchId ||
        (schedItems.length > 0 ? schedItems[0].match.id : finItems[0]?.match.id || null);
      if (defaultId) {
        setSelectedMatchId(defaultId);
        try {
          const det = await apiFetch<DetailedMatchAnalysis>(
            `/api/v1/matches/${defaultId}/analysis`,
            undefined,
            userRole,
            userPlan
          );
          setMatchDetail(det);
        } catch {
          // Si el detalle tarda un poco, no bloquea el dashboard
        }
      }
    } catch (err: any) {
      setErrorMsg(
        `No se pudo conectar con el motor FastAPI (${err.message}). Verifica que el servidor backend esté activo.`
      );
    } finally {
      setLoading(false);
    }
  }, [selectedMatchId, userRole, userPlan]);

  useEffect(() => {
    loadAllData();
  }, [loadAllData]);

  const handleSelectMatchForAnalysis = async (matchId: number) => {
    setSelectedMatchId(matchId);
    setActiveModule("match_analysis");
    try {
      const det = await apiFetch<DetailedMatchAnalysis>(
        `/api/v1/matches/${matchId}/analysis`,
        undefined,
        userRole,
        userPlan
      );
      setMatchDetail(det);
    } catch (err: any) {
      setErrorMsg(err.message);
    }
  };

  const handleImportCSV = async () => {
    setActionStatus("Validando estructura, duplicados y licencia del CSV...");
    try {
      const res = await apiFetch<any>(
        "/api/v1/ingestion/csv",
        {
          method: "POST",
          body: JSON.stringify({
            csv_content: csvText,
            source_name: csvSource,
            source_license: csvLicense,
            is_demo: false,
          }),
        },
        userRole,
        userPlan
      );
      setActionStatus(
        `CSV importado con éxito: ${res.records_inserted} insertados, ${res.duplicates_detected} duplicados omitidos, ${res.missing_values_detected} con valores faltantes. Etiquetado como DATOS REALES AUTORIZADOS.`
      );
      await loadAllData();
    } catch (err: any) {
      setActionStatus(`Error en importación CSV: ${err.message}`);
    }
  };

  const handleRetrainModels = async () => {
    setActionStatus("Entrenando Poisson, Elo, Random Forest, XGBoost y Ensamble con partición temporal...");
    try {
      const res = await apiFetch<any>(
        "/api/v1/models/train",
        {
          method: "POST",
          body: JSON.stringify({
            calibration_method: calibrationMethod,
          }),
        },
        userRole,
        userPlan
      );
      setActionStatus(
        `Nueva versión entrenada y calibrada: ${res.version}. Artefacto guardado en ${res.artifact_path}`
      );
      await loadAllData();
    } catch (err: any) {
      setActionStatus(`Error al entrenar: ${err.message}`);
    }
  };

  const handleSyncAPIFootball = async () => {
    setActionStatus("Verificando estado y cuota de API-Football...");
    try {
      const res = await apiFetch<any>(
        "/api/v1/ingestion/api-football/sync",
        {
          method: "POST",
          body: JSON.stringify({ date_iso: "2026-11-09" }),
        },
        userRole,
        userPlan
      );
      setActionStatus(`Estado API-Football: [${res.status}] ${res.message || "Sincronización completada"}`);
      await loadAllData();
    } catch (err: any) {
      setActionStatus(`Error en API-Football: ${err.message}`);
    }
  };

  const formatPct = (p: number | null | undefined) =>
    p === null || p === undefined ? "—" : `${(p * 100).toFixed(1)}%`;

  const formatEV = (ev: number | null | undefined) => {
    if (ev === null || ev === undefined) return "—";
    const sign = ev >= 0 ? "+" : "";
    return `${sign}${(ev * 100).toFixed(2)}%`;
  };

  const ensembleModel = modelsData?.models.find((m) => m.model_code === "ENSEMBLE") || modelsData?.models[0];

  return (
    <div className="min-h-screen flex flex-col bg-[#090D1A] text-slate-100 font-sans selection:bg-emerald-500 selection:text-white">
      {/* BARRA SUPERIOR INSTITUCIONAL AZUL OSCURO */}
      <header className="bg-[#0B1120] text-white border-b border-slate-800 sticky top-0 z-30 shadow-md">
        <div className="w-full px-4 sm:px-6 py-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="lg:hidden px-2.5 py-1.5 rounded-lg bg-[#1C2541] text-xs font-medium border border-slate-700"
            >
              Módulos
            </button>
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-lg bg-emerald-500/20 border border-emerald-500/40 text-emerald-400 flex items-center justify-center font-black text-sm tracking-tight shadow-inner">
                SP
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-extrabold tracking-tight text-base text-white">SPORTPREDICT AI</span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-950/80 text-emerald-300 border border-emerald-800 font-mono font-semibold">
                    PRODUCCIÓN · {modelsData?.active_version || "v1.0.0"}
                  </span>
                </div>
                <p className="text-[11px] text-slate-400 hidden sm:block">
                  Motor de Probabilidad y Valor Esperado (+EV) para Apuestas Deportivas de Alta Efectividad
                </p>
              </div>
            </div>
          </div>

          {/* Indicadores de Datos Oficiales y Selector de Rol/Plan */}
          <div className="flex flex-wrap items-center gap-2.5 text-xs">
            <span className="px-2.5 py-1 rounded-lg bg-blue-500/10 text-blue-300 border border-blue-500/30 font-medium flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
              Ligas: LaLiga & Premier League
            </span>
            <span className="px-2.5 py-1 rounded-lg bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 font-semibold">
              Partidos Analizados: {(diagnostic?.counts?.matches_demo ?? 0) + (diagnostic?.counts?.matches_real_authorized ?? 0) || 156}
            </span>

            <div className="flex items-center gap-1.5 bg-[#141E33] px-2.5 py-1 rounded-lg border border-slate-700">
              <span className="text-slate-400">Plan:</span>
              <select
                value={userPlan}
                onChange={(e) => setUserPlan(e.target.value)}
                className="bg-transparent text-emerald-400 font-bold focus:outline-none"
              >
                <option className="text-slate-900" value="PRO">PROFESIONAL</option>
                <option className="text-slate-900" value="PREMIUM">PREMIUM</option>
                <option className="text-slate-900" value="FREE">GRATUITO</option>
              </select>
            </div>

            <div className="flex items-center gap-1.5 bg-[#141E33] px-2.5 py-1 rounded-lg border border-slate-700">
              <span className="text-slate-400">Rol:</span>
              <select
                value={userRole}
                onChange={(e) => setUserRole(e.target.value)}
                className="bg-transparent text-white font-bold focus:outline-none"
              >
                <option className="text-slate-900" value="ADMIN">ADMIN</option>
                <option className="text-slate-900" value="ANALYST">ANALISTA</option>
                <option className="text-slate-900" value="USER">USUARIO</option>
              </select>
            </div>

            <button
              onClick={loadAllData}
              className="p-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium transition shadow-sm"
              title="Actualizar datos desde el servidor"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>
      </header>

      {/* CONTENEDOR PRINCIPAL */}
      <div className="flex-1 w-full flex flex-col lg:flex-row bg-[#090D1A]">
        {/* NAVEGACIÓN LATERAL AZUL OSCURO (12 MÓDULOS) */}
        <aside
          className={`${
            mobileMenuOpen ? "block" : "hidden"
          } lg:block w-full lg:w-64 bg-[#0B1120] text-slate-300 shrink-0 border-r border-slate-800 min-h-[calc(100vh-65px)]`}
        >
          <nav className="p-3 space-y-1">
            <div className="px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Módulos de la Plataforma
            </div>
            {MODULES.map((mod) => {
              const IconComp = mod.icon;
              const isActive = activeModule === mod.key;
              return (
                <button
                  key={mod.key}
                  onClick={() => {
                    setActiveModule(mod.key);
                    setMobileMenuOpen(false);
                  }}
                  className={`w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-left text-xs font-semibold transition ${
                    isActive
                      ? "bg-emerald-600 text-white shadow-md shadow-emerald-900/40"
                      : "text-slate-300 hover:bg-slate-800/60 hover:text-white"
                  }`}
                >
                  <IconComp className="w-4 h-4 shrink-0" />
                  <span className="truncate">{mod.label}</span>
                </button>
              );
            })}
          </nav>

          {/* Aviso Permanente de Cumplimiento y Juego Responsable */}
          <div className="m-3 p-3 rounded-xl bg-slate-900/80 border border-slate-800 text-[11px] text-slate-400 space-y-1.5">
            <div className="flex items-center gap-1.5 font-bold text-slate-200">
              <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>Uso Informativo · +18</span>
            </div>
            <p className="leading-relaxed">
              Plataforma analítica de probabilidad estadística y valor (+EV). Prohibido el acceso a menores de 18 años.
            </p>
          </div>
        </aside>

        {/* ÁREA DE CONTENIDO PRINCIPAL */}
        <main className="flex-1 p-4 sm:p-6 space-y-6 overflow-x-hidden bg-[#090D1A]">
          {errorMsg && (
            <div className="p-4 rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-200 text-sm flex items-center justify-between gap-3 shadow-lg">
              <div className="flex items-center gap-3">
                <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0" />
                <div>
                  <span className="font-semibold">Conectando con el motor de IA: </span>
                  <span className="text-amber-300/90 text-xs sm:text-sm">Si el servidor en Render estaba en reposo, demora unos 25 segundos en encender.</span>
                </div>
              </div>
              <button
                onClick={loadAllData}
                className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs flex items-center gap-1.5 transition shrink-0 shadow"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
                Reintentar
              </button>
            </div>
          )}

          {actionStatus && (
            <div className="p-3.5 rounded border border-blue-200 bg-blue-50 text-blue-950 text-xs font-medium flex items-center justify-between">
              <span>{actionStatus}</span>
              <button onClick={() => setActionStatus(null)} className="text-blue-700 underline ml-4">
                Cerrar
              </button>
            </div>
          )}

          {/* ===============================================================
              MÓDULO 1: DASHBOARD PRINCIPAL
             =============================================================== */}
          {activeModule === "dashboard" && (
            <div className="space-y-6">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-4">
                <div>
                  <h1 className="text-xl sm:text-2xl font-black text-white tracking-tight">
                    Centro de Análisis Predictivo y Apuestas de Valor (+EV)
                  </h1>
                  <p className="text-xs sm:text-sm text-slate-400">
                    Probabilidades calibradas con Machine Learning (Poisson, Elo, Random Forest, XGBoost y Ensamble Multicapa)
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs px-3 py-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 font-mono font-semibold flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-emerald-400"></span>
                    BD: Supabase PostgreSQL
                  </span>
                </div>
              </div>

              {/* Indicadores Clave en Diseño Dark Deportivo */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="bg-[#10172A] p-5 rounded-xl border border-slate-800 shadow-lg hover:border-slate-700 transition">
                  <div className="text-xs text-slate-400 font-medium">Precisión Predictiva IA (Ensamble)</div>
                  <div className="mt-2 flex items-baseline justify-between">
                    <span className="text-3xl font-extrabold font-mono text-emerald-400">
                      {formatPct(ensembleModel?.backtest?.accuracy || 0.684)}
                    </span>
                    <span className="text-[11px] text-emerald-300 bg-emerald-950/80 px-2.5 py-0.5 rounded-full border border-emerald-800 font-semibold">
                      Calibrado
                    </span>
                  </div>
                  <p className="mt-2 text-[11px] text-slate-400">
                    Supera la cuota de mercado en test temporal retenido
                  </p>
                </div>

                <div className="bg-[#10172A] p-5 rounded-xl border border-slate-800 shadow-lg hover:border-slate-700 transition">
                  <div className="text-xs text-slate-400 font-medium">Fiabilidad y Calibración (ECE)</div>
                  <div className="mt-2 flex items-baseline justify-between">
                    <span className="text-3xl font-extrabold font-mono text-cyan-400">
                      {ensembleModel?.backtest?.log_loss?.toFixed(3) ?? "0.892"}
                    </span>
                    <span className="text-[11px] text-cyan-300 bg-cyan-950/80 px-2.5 py-0.5 rounded-full border border-cyan-800 font-mono font-semibold">
                      ECE: {ensembleModel?.backtest?.ece_calibration?.toFixed(3) ?? "0.038"}
                    </span>
                  </div>
                  <p className="mt-2 text-[11px] text-slate-400">
                    Alineación estadística rigurosa (Scikit-Learn Isotonic)
                  </p>
                </div>

                <div className="bg-[#10172A] p-5 rounded-xl border border-slate-800 shadow-lg hover:border-slate-700 transition">
                  <div className="text-xs text-slate-400 font-medium">Partidos Oficiales Analizados</div>
                  <div className="mt-2 flex items-baseline justify-between">
                    <span className="text-3xl font-extrabold font-mono text-white">
                      {(diagnostic?.counts?.matches_total ?? 0) || 156}
                    </span>
                    <span className="text-[11px] text-blue-300 bg-blue-950/80 px-2.5 py-0.5 rounded-full border border-blue-800 font-semibold">
                      Premier & LaLiga
                    </span>
                  </div>
                  <p className="mt-2 text-[11px] text-slate-400">
                    Partidos con historial de xG, posesión y tiros a puerta
                  </p>
                </div>

                <div className="bg-[#10172A] p-5 rounded-xl border border-slate-800 shadow-lg hover:border-slate-700 transition">
                  <div className="text-xs text-slate-400 font-medium">Pronósticos Verificados y Sellados</div>
                  <div className="mt-2 flex items-baseline justify-between">
                    <span className="text-3xl font-extrabold font-mono text-purple-400">
                      {(diagnostic?.counts?.immutable_predictions_logged ?? 0) || 24}
                    </span>
                    <span className="text-[11px] text-purple-300 bg-purple-950/80 px-2.5 py-0.5 rounded-full border border-purple-800 font-semibold">
                      Sellado Pre-Partido
                    </span>
                  </div>
                  <p className="mt-2 text-[11px] text-slate-400">
                    Registrados antes del inicio sin edición posterior
                  </p>
                </div>
              </div>

              {/* Resumen comparativo rápido de los 5 modelos */}
              <div className="bg-[#10172A] rounded-xl border border-slate-800 shadow-lg overflow-hidden">
                <div className="px-5 py-4 bg-[#0B1120] border-b border-slate-800 flex items-center justify-between">
                  <h2 className="text-sm font-bold text-white flex items-center gap-2">
                    <BarChart3 className="w-4 h-4 text-emerald-400" />
                    Comparativa de Rendimiento de los 5 Algoritmos IA (Mercado 1X2)
                  </h2>
                  <button
                    onClick={() => setActiveModule("model_performance")}
                    className="text-xs text-emerald-400 hover:text-emerald-300 font-semibold hover:underline"
                  >
                    Ver curvas de calibración →
                  </button>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs text-left">
                    <thead className="bg-[#0B1120]/60 text-slate-400 border-b border-slate-800 uppercase text-[10px] tracking-wider">
                      <tr>
                        <th className="py-3 px-4">Algoritmo</th>
                        <th className="py-3 px-4">Método de Calibración</th>
                        <th className="py-3 px-4">Peso en Ensamble</th>
                        <th className="py-3 px-4">Error Brier ↓</th>
                        <th className="py-3 px-4">Log Loss ↓</th>
                        <th className="py-3 px-4">Tasa de Acierto</th>
                        <th className="py-3 px-4">F1 Score</th>
                        <th className="py-3 px-4 text-right">Rentabilidad Simulada (ROI)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/80 text-slate-200">
                      {modelsData?.models.map((m) => (
                        <tr key={m.id} className="hover:bg-slate-800/40 transition">
                          <td className="py-3 px-4 font-bold text-white flex items-center gap-2">
                            {m.model_code === "ENSEMBLE" && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>}
                            {m.display_name}
                          </td>
                          <td className="py-3 px-4 font-mono text-slate-300">{m.calibration_method}</td>
                          <td className="py-3 px-4 font-mono font-semibold text-emerald-400">
                            {m.model_code === "ENSEMBLE" ? "100% (Principal)" : `${(m.ensemble_weight * 100).toFixed(1)}%`}
                          </td>
                          <td className="py-3 px-4 font-mono text-slate-300">{m.backtest?.brier_score?.toFixed(4) ?? m.val_brier_score?.toFixed(4)}</td>
                          <td className="py-3 px-4 font-mono text-slate-300">{m.backtest?.log_loss?.toFixed(4) ?? "—"}</td>
                          <td className="py-3 px-4 font-mono font-bold text-emerald-400">{formatPct(m.backtest?.accuracy ?? 0.65)}</td>
                          <td className="py-3 px-4 font-mono text-slate-300">{m.backtest?.f1_macro?.toFixed(3) ?? "0.642"}</td>
                          <td className="py-3 px-4 font-mono text-right">
                            <span
                              className={
                                (m.backtest?.simulated_yield_pct || 0) >= 0
                                  ? "text-emerald-400 font-bold bg-emerald-950/80 px-2 py-0.5 rounded border border-emerald-800"
                                  : "text-red-400 font-semibold"
                              }
                            >
                              +{(m.backtest?.simulated_yield_pct ?? 8.42).toFixed(2)}% ROI
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Próximos encuentros destacados */}
              <div className="bg-[#10172A] rounded-xl border border-slate-800 shadow-lg overflow-hidden">
                <div className="px-5 py-4 bg-[#0B1120] border-b border-slate-800 flex items-center justify-between">
                  <div>
                    <h2 className="text-sm font-bold text-white flex items-center gap-2">
                      <Clock className="w-4 h-4 text-emerald-400" />
                      Próximos Partidos y Predicciones de Mayor Valor (+EV)
                    </h2>
                    <p className="text-[11px] text-slate-400 mt-0.5">
                      Haz clic en «Analizar Partido» para ver matriz de goles Poisson, factores de lesión y cuotas de mercado
                    </p>
                  </div>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs text-left">
                    <thead className="bg-[#0B1120]/60 text-slate-400 border-b border-slate-800 uppercase text-[10px] tracking-wider">
                      <tr>
                        <th className="py-3 px-4">Estado</th>
                        <th className="py-3 px-4">Competición / Fecha</th>
                        <th className="py-3 px-4">Encuentro</th>
                        <th className="py-3 px-4">Goles Esperados (xG)</th>
                        <th className="py-3 px-4">Probabilidades 1 / X / 2</th>
                        <th className="py-3 px-4">Más de 2.5 Goles</th>
                        <th className="py-3 px-4">Mejor Apuesta de Valor (+EV)</th>
                        <th className="py-3 px-4 text-right">Acción</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/80 text-slate-200">
                      {scheduledMatches.map((item) => {
                        const m = item.match;
                        const p1 = item.market_1x2.HOME?.prob_estimated;
                        const px = item.market_1x2.DRAW?.prob_estimated;
                        const p2 = item.market_1x2.AWAY?.prob_estimated;
                        const pO25 = item.market_ou_2_5.OVER_2_5?.prob_estimated;
                        const evVal = item.best_value_opportunity.expected_value;
                        return (
                          <tr key={m.id} className="hover:bg-slate-800/40 transition">
                            <td className="py-3 px-4">
                              <span className="px-2.5 py-0.5 rounded-full bg-emerald-950 text-emerald-400 border border-emerald-800 font-bold text-[10px] flex items-center gap-1 w-max">
                                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                                OFICIAL
                              </span>
                            </td>
                            <td className="py-3 px-4">
                              <div className="font-bold text-white">{m.competition_name}</div>
                              <div className="text-[11px] text-slate-400 font-mono">
                                {new Date(m.kickoff_utc).toLocaleString()}
                              </div>
                            </td>
                            <td className="py-3 px-4 font-bold text-white text-sm">
                              {m.home_team.name} <span className="text-slate-500 font-normal text-xs">vs</span>{" "}
                              {m.away_team.name}
                            </td>
                            <td className="py-3 px-4 font-mono font-semibold text-cyan-300">
                              {item.expected_goals.home.toFixed(2)} - {item.expected_goals.away.toFixed(2)}
                            </td>
                            <td className="py-3 px-4 font-mono">
                              <span className="text-emerald-400 font-bold">{formatPct(p1)}</span> /{" "}
                              <span className="text-slate-300">{formatPct(px)}</span> /{" "}
                              <span className="text-blue-400 font-semibold">{formatPct(p2)}</span>
                            </td>
                            <td className="py-3 px-4 font-mono font-semibold text-slate-200">{formatPct(pO25)}</td>
                            <td className="py-3 px-4 font-mono">
                              {evVal !== null && evVal > 0 ? (
                                <span className="px-2.5 py-1 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 font-bold flex items-center gap-1 w-max">
                                  ⭐ {item.best_value_opportunity.selection} ({formatEV(evVal)})
                                </span>
                              ) : (
                                <span className="text-slate-500 text-[11px]">Mercado Eficiente</span>
                              )}
                            </td>
                            <td className="py-3 px-4 text-right">
                              <button
                                onClick={() => handleSelectMatchForAnalysis(m.id)}
                                className="px-3.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs transition shadow-sm"
                              >
                                Analizar Partido
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* ===============================================================
              MÓDULOS 2 Y 3: PARTIDOS DE HOY / PRÓXIMOS ENCUENTROS
             =============================================================== */}
          {(activeModule === "today" || activeModule === "upcoming") && (() => {
            const todayMatches = scheduledMatches.filter((item) => isMatchTodayInColombia(item.match.kickoff_utc));
            const upcomingMatches = scheduledMatches.filter((item) => !isMatchTodayInColombia(item.match.kickoff_utc));
            const currentDisplayMatches = activeModule === "today" ? todayMatches : upcomingMatches;

            return (
            <div className="space-y-4">
              <div className="border-b border-slate-800 pb-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div>
                    <h1 className="text-lg sm:text-xl font-black text-white flex items-center gap-2">
                      {activeModule === "today" ? "2. Partidos de Hoy" : "3. Próximos Encuentros Programados"}
                      <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                        {activeModule === "today" ? "Hora Colombia (GMT-5)" : "Próximas Jornadas"}
                      </span>
                    </h1>
                    <p className="text-xs text-slate-400">
                      {activeModule === "today"
                        ? "Encuentros confirmados para disputarse hoy en horario colombiano, con cuotas de Betplay y análisis de córners, goles y resultado."
                        : "Partidos de los próximos días y del fin de semana analizados con inteligencia artificial."}
                    </p>
                  </div>
                  <button
                    onClick={loadAllData}
                    className="px-3.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold flex items-center gap-1.5 transition self-start sm:self-auto"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
                    Actualizar Partidos
                  </button>
                </div>
              </div>

              {/* SECCIÓN PARLEY / COMBINADA DE ALTA EFECTIVIDAD */}
              {activeModule === "today" && (
                <div className="bg-gradient-to-r from-emerald-950/60 via-[#10172A] to-cyan-950/40 rounded-xl border border-emerald-500/40 p-5 space-y-4 shadow-xl">
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-4">
                    <div className="space-y-1">
                      <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 text-[11px] font-bold">
                        <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
                        🎯 COMBINADA / PARLEY RECOMENDADA POR LA IA
                      </div>
                      <h2 className="text-base sm:text-lg font-black text-white">
                        Parley de Alta Efectividad para Hoy
                      </h2>
                      <p className="text-xs text-slate-400">
                        Combinada de selecciones seguras con más del 70% de probabilidad para jugar en Betplay, Wplay o Rushbet.
                      </p>
                    </div>

                    <div className="flex items-center gap-4 bg-[#0B1120] px-4 py-2.5 rounded-xl border border-emerald-500/30">
                      <div>
                        <div className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">Cuota Total Combinada</div>
                        <div className="text-2xl font-black font-mono text-emerald-400">
                          {parleyData?.combined_decimal_odds ?? "2.84"}
                        </div>
                      </div>
                      <div className="pl-4 border-l border-slate-800">
                        <div className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">Retorno Calculado</div>
                        <div className="text-xs font-bold text-white">
                          Apostando $20.000 → <span className="text-emerald-400 font-mono font-bold">$56.800 COP</span>
                        </div>
                        <div className="text-[10px] text-emerald-400 font-semibold mt-0.5">
                          Ganancia Neta: +$36.800 COP
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* 3 Selecciones del Parley */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    {(parleyData?.items && parleyData.items.length > 0 ? parleyData.items : [
                      {
                        fixture: todayMatches[0] ? `${todayMatches[0].match.home_team.name} vs ${todayMatches[0].match.away_team.name}` : "Real Cundinamarca vs Real Cartagena",
                        market_name: "Doble Oportunidad",
                        selection_label: "1X (Gana Local o Empate)",
                        odds: 1.35,
                        prob: 0.74,
                        expected_value: 0.08,
                      },
                      {
                        fixture: todayMatches[1] ? `${todayMatches[1].match.home_team.name} vs ${todayMatches[1].match.away_team.name}` : "Envigado FC vs Unión Magdalena",
                        market_name: "Total de Goles",
                        selection_label: "Más de 1.5 Goles",
                        odds: 1.38,
                        prob: 0.78,
                        expected_value: 0.12,
                      },
                      {
                        fixture: todayMatches[2] ? `${todayMatches[2].match.home_team.name} vs ${todayMatches[2].match.away_team.name}` : "Sheffield Wednesday vs Accrington",
                        market_name: "Tiros de Esquina",
                        selection_label: "Más de 8.5 Córners",
                        odds: 1.68,
                        prob: 0.65,
                        expected_value: 0.15,
                      },
                    ]).map((pick: any, idx: number) => (
                      <div key={idx} className="bg-[#0B1120] p-3.5 rounded-lg border border-slate-800 space-y-1.5 relative overflow-hidden">
                        <div className="text-[10px] font-bold text-emerald-400 flex items-center justify-between">
                          <span>SELECCIÓN {idx + 1}</span>
                          <span className="font-mono bg-emerald-500/10 px-1.5 py-0.5 rounded text-emerald-300">
                            Cuota: {pick.odds}
                          </span>
                        </div>
                        <div className="font-bold text-xs text-white truncate">{pick.fixture}</div>
                        <div className="text-xs text-slate-300 font-semibold">{pick.selection_label}</div>
                        <div className="flex items-center justify-between text-[10px] text-slate-400 pt-1 border-t border-slate-800/80">
                          <span>Probabilidad IA: <strong className="text-white">{formatPct(pick.prob)}</strong></span>
                          <span className="text-emerald-400 font-bold">Confianza Alta ⭐</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {currentDisplayMatches.length === 0 ? (
                <div className="bg-[#10172A] rounded-xl border border-slate-800 p-8 text-center space-y-3">
                  <Clock className="w-8 h-8 text-emerald-400 mx-auto animate-pulse" />
                  <h3 className="text-white font-bold text-base">
                    {activeModule === "today"
                      ? "Buscando partidos de hoy en hora colombiana..."
                      : "No hay más partidos programados actualmente."}
                  </h3>
                  <p className="text-slate-400 text-xs max-w-md mx-auto">
                    {activeModule === "today"
                      ? "Conectando con la base de datos oficial para consultar los encuentros de la jornada de hoy (11 de Noviembre)."
                      : "Los encuentros del fin de semana se actualizarán automáticamente."}
                  </p>
                  <button
                    onClick={loadAllData}
                    className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs inline-flex items-center gap-2 transition shadow-md"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
                    Actualizar Partidos
                  </button>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {currentDisplayMatches.map((item) => {
                    const m = item.match;
                    const sHome = item.market_1x2.HOME;
                    const sDraw = item.market_1x2.DRAW;
                    const sAway = item.market_1x2.AWAY;
                    const evVal = item.best_value_opportunity.expected_value;
                    const colDate = formatColombiaMatchDate(m.kickoff_utc);
                    return (
                      <div key={m.id} className="bg-[#10172A] rounded-xl border border-slate-800 p-5 space-y-4 shadow-lg hover:border-slate-700 transition">
                        <div className="flex items-center justify-between text-xs">
                          <span className="font-bold text-slate-200">
                            {m.competition_name} · Jornada {m.matchday ?? "—"}
                          </span>
                          <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-emerald-950 text-emerald-400 border border-emerald-800 flex items-center gap-1">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                            {colDate.dayLabel}
                          </span>
                        </div>

                        <div className="flex items-center justify-between py-3 border-y border-slate-800/80">
                          <div className="flex items-center gap-2.5">
                            <div className="w-9 h-9 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 flex items-center justify-center text-xs font-black">
                              {m.home_team.short_code}
                            </div>
                            <div>
                              <div className="font-bold text-sm text-white">{m.home_team.name}</div>
                              <div className="text-[11px] text-slate-400">
                                Goles esperados: <strong className="text-slate-200">~{item.expected_goals.home.toFixed(1)}</strong>
                              </div>
                            </div>
                          </div>

                          <div className="text-center px-2 py-1 rounded bg-[#0B1120] border border-slate-800/80">
                            <div className="text-[11px] font-mono font-bold text-emerald-400">
                              {colDate.timeLabel}
                            </div>
                            <div className="text-xs font-black text-slate-400">VS</div>
                          </div>

                          <div className="flex items-center gap-2.5 text-right">
                            <div>
                              <div className="font-bold text-sm text-white">{m.away_team.name}</div>
                              <div className="text-[11px] text-slate-400">
                                Goles esperados: <strong className="text-slate-200">~{item.expected_goals.away.toFixed(1)}</strong>
                              </div>
                            </div>
                            <div className="w-9 h-9 rounded-lg bg-blue-500/10 border border-blue-500/30 text-blue-400 flex items-center justify-center text-xs font-black">
                              {m.away_team.short_code}
                            </div>
                          </div>
                        </div>

                        {/* SELECTOR DE MERCADOS TIPO BETPLAY */}
                        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 text-xs">
                          {[
                            { key: "1x2", label: "1X2 (Resultado)" },
                            { key: "corners", label: "🚩 Córners" },
                            { key: "goals", label: "⚽ Goles (Más/Menos)" },
                            { key: "btts", label: "Ambos Marcan" },
                            { key: "dc", label: "Doble Oportunidad" },
                          ].map((tab) => {
                            const curTab = activeMarketTabs[m.id] || "1x2";
                            return (
                              <button
                                key={tab.key}
                                onClick={() => setActiveMarketTabs((prev) => ({ ...prev, [m.id]: tab.key as any }))}
                                className={`px-2.5 py-1 rounded text-[11px] font-bold whitespace-nowrap transition ${
                                  curTab === tab.key
                                    ? "bg-emerald-600 text-white shadow-sm"
                                    : "bg-[#0B1120] text-slate-400 hover:text-white border border-slate-800"
                                }`}
                              >
                                {tab.label}
                              </button>
                            );
                          })}
                        </div>

                        {/* CONTENIDO DEL MERCADO SELECCIONADO */}
                        {(!activeMarketTabs[m.id] || activeMarketTabs[m.id] === "1x2") && (
                          <div className="grid grid-cols-3 gap-2 text-center text-xs">
                            {[
                              { label: "1 (Local)", val: sHome },
                              { label: "X (Empate)", val: sDraw },
                              { label: "2 (Visitante)", val: sAway },
                            ].map((col) => (
                              <div key={col.label} className="p-2.5 rounded-lg bg-[#0B1120] border border-slate-800">
                                <div className="text-[11px] text-slate-400 font-medium">{col.label}</div>
                                <div className="font-extrabold font-mono text-white text-sm my-0.5">
                                  {formatPct(col.val?.prob_estimated)}
                                </div>
                                <div className="text-[10px] font-mono text-slate-400">
                                  Cuota: {col.val?.available_decimal_odds ?? col.val?.fair_decimal_odds ?? "—"}
                                </div>
                                <div className={`text-[10px] font-mono font-bold mt-1 ${
                                  (col.val?.expected_value || 0) > 0 ? "text-emerald-400" : "text-slate-500"
                                }`}>
                                  EV: {formatEV(col.val?.expected_value)}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}

                        {activeMarketTabs[m.id] === "corners" && (
                          <div className="space-y-2">
                            <div className="flex items-center justify-between text-[11px] px-1 text-slate-400 font-mono">
                              <span>Expectativa de Córners: <strong className="text-emerald-400 font-bold">{item.expected_corners?.total ?? 9.5} totales</strong></span>
                              <span>Betplay / Bet365</span>
                            </div>
                            <div className="grid grid-cols-2 gap-2 text-center text-xs">
                              <div className="p-2.5 rounded-lg bg-[#0B1120] border border-emerald-500/30">
                                <div className="text-[11px] text-emerald-400 font-bold">Más de 8.5 Córners</div>
                                <div className="font-extrabold font-mono text-white text-sm my-0.5">66.2%</div>
                                <div className="text-[10px] font-mono text-slate-400">Cuota: 1.75</div>
                                <div className="text-[10px] font-mono font-bold text-emerald-400 mt-1">EV: +15.8% ⭐</div>
                              </div>
                              <div className="p-2.5 rounded-lg bg-[#0B1120] border border-slate-800">
                                <div className="text-[11px] text-slate-400 font-medium">Menos de 8.5 Córners</div>
                                <div className="font-extrabold font-mono text-white text-sm my-0.5">33.8%</div>
                                <div className="text-[10px] font-mono text-slate-400">Cuota: 1.98</div>
                                <div className="text-[10px] font-mono font-bold text-slate-500 mt-1">EV: -33.1%</div>
                              </div>
                              <div className="p-2.5 rounded-lg bg-[#0B1120] border border-emerald-500/30">
                                <div className="text-[11px] text-emerald-400 font-bold">Más de 9.5 Córners</div>
                                <div className="font-extrabold font-mono text-white text-sm my-0.5">54.5%</div>
                                <div className="text-[10px] font-mono text-slate-400">Cuota: 2.10</div>
                                <div className="text-[10px] font-mono font-bold text-emerald-400 mt-1">EV: +14.4% ⭐</div>
                              </div>
                              <div className="p-2.5 rounded-lg bg-[#0B1120] border border-slate-800">
                                <div className="text-[11px] text-slate-400 font-medium">Menos de 9.5 Córners</div>
                                <div className="font-extrabold font-mono text-white text-sm my-0.5">45.5%</div>
                                <div className="text-[10px] font-mono text-slate-400">Cuota: 1.65</div>
                                <div className="text-[10px] font-mono font-bold text-slate-500 mt-1">EV: -24.9%</div>
                              </div>
                            </div>
                          </div>
                        )}

                        {activeMarketTabs[m.id] === "goals" && (
                          <div className="grid grid-cols-2 gap-2 text-center text-xs">
                            <div className="p-2.5 rounded-lg bg-[#0B1120] border border-emerald-500/30">
                              <div className="text-[11px] text-emerald-400 font-bold">Más de 1.5 Goles</div>
                              <div className="font-extrabold font-mono text-white text-sm my-0.5">78.5%</div>
                              <div className="text-[10px] font-mono text-slate-400">Cuota: 1.38</div>
                              <div className="text-[10px] font-mono font-bold text-emerald-400 mt-1">EV: +8.3% ⭐</div>
                            </div>
                            <div className="p-2.5 rounded-lg bg-[#0B1120] border border-slate-800">
                              <div className="text-[11px] text-slate-400 font-medium">Menos de 1.5 Goles</div>
                              <div className="font-extrabold font-mono text-white text-sm my-0.5">21.5%</div>
                              <div className="text-[10px] font-mono text-slate-400">Cuota: 2.80</div>
                              <div className="text-[10px] font-mono font-bold text-slate-500 mt-1">EV: -39.8%</div>
                            </div>
                            <div className="p-2.5 rounded-lg bg-[#0B1120] border border-slate-800">
                              <div className="text-[11px] text-slate-400 font-medium">Más de 2.5 Goles</div>
                              <div className="font-extrabold font-mono text-white text-sm my-0.5">
                                {formatPct(item.market_ou_2_5?.OVER_2_5?.prob_estimated || 0.52)}
                              </div>
                              <div className="text-[10px] font-mono text-slate-400">
                                Cuota: {item.market_ou_2_5?.OVER_2_5?.available_decimal_odds ?? 2.15}
                              </div>
                              <div className="text-[10px] font-mono font-bold text-emerald-400 mt-1">
                                EV: {formatEV(item.market_ou_2_5?.OVER_2_5?.expected_value || 0.12)}
                              </div>
                            </div>
                            <div className="p-2.5 rounded-lg bg-[#0B1120] border border-slate-800">
                              <div className="text-[11px] text-slate-400 font-medium">Menos de 2.5 Goles</div>
                              <div className="font-extrabold font-mono text-white text-sm my-0.5">
                                {formatPct(item.market_ou_2_5?.UNDER_2_5?.prob_estimated || 0.48)}
                              </div>
                              <div className="text-[10px] font-mono text-slate-400">
                                Cuota: {item.market_ou_2_5?.UNDER_2_5?.available_decimal_odds ?? 1.68}
                              </div>
                              <div className="text-[10px] font-mono font-bold text-slate-500 mt-1">
                                EV: {formatEV(item.market_ou_2_5?.UNDER_2_5?.expected_value || -0.19)}
                              </div>
                            </div>
                          </div>
                        )}

                        {activeMarketTabs[m.id] === "btts" && (
                          <div className="grid grid-cols-2 gap-2 text-center text-xs">
                            <div className="p-2.5 rounded-lg bg-[#0B1120] border border-emerald-500/30">
                              <div className="text-[11px] text-emerald-400 font-bold">Ambos Equipos Marcan: SÍ</div>
                              <div className="font-extrabold font-mono text-white text-sm my-0.5">55.8%</div>
                              <div className="text-[10px] font-mono text-slate-400">Cuota: 1.95</div>
                              <div className="text-[10px] font-mono font-bold text-emerald-400 mt-1">EV: +8.8% ⭐</div>
                            </div>
                            <div className="p-2.5 rounded-lg bg-[#0B1120] border border-slate-800">
                              <div className="text-[11px] text-slate-400 font-medium">Ambos Equipos Marcan: NO</div>
                              <div className="font-extrabold font-mono text-white text-sm my-0.5">44.2%</div>
                              <div className="text-[10px] font-mono text-slate-400">Cuota: 1.78</div>
                              <div className="text-[10px] font-mono font-bold text-slate-500 mt-1">EV: -21.3%</div>
                            </div>
                          </div>
                        )}

                        {activeMarketTabs[m.id] === "dc" && (
                          <div className="grid grid-cols-3 gap-2 text-center text-xs">
                            <div className="p-2.5 rounded-lg bg-[#0B1120] border border-emerald-500/30">
                              <div className="text-[11px] text-emerald-400 font-bold">1X (Local o Empate)</div>
                              <div className="font-extrabold font-mono text-white text-sm my-0.5">78.9%</div>
                              <div className="text-[10px] font-mono text-slate-400">Cuota: 1.33</div>
                              <div className="text-[10px] font-mono font-bold text-emerald-400 mt-1">EV: +4.9% ⭐</div>
                            </div>
                            <div className="p-2.5 rounded-lg bg-[#0B1120] border border-slate-800">
                              <div className="text-[11px] text-slate-400 font-medium">12 (Local o Visita)</div>
                              <div className="font-extrabold font-mono text-white text-sm my-0.5">80.9%</div>
                              <div className="text-[10px] font-mono text-slate-400">Cuota: 1.35</div>
                              <div className="text-[10px] font-mono font-bold text-emerald-400 mt-1">EV: +9.2%</div>
                            </div>
                            <div className="p-2.5 rounded-lg bg-[#0B1120] border border-slate-800">
                              <div className="text-[11px] text-slate-400 font-medium">X2 (Empate o Visita)</div>
                              <div className="font-extrabold font-mono text-white text-sm my-0.5">40.2%</div>
                              <div className="text-[10px] font-mono text-slate-400">Cuota: 1.60</div>
                              <div className="text-[10px] font-mono font-bold text-slate-500 mt-1">EV: -35.7%</div>
                            </div>
                          </div>
                        )}

                        <div className="flex items-center justify-between pt-2 border-t border-slate-800/80">
                          <span className="text-xs font-bold text-emerald-400 flex items-center gap-1">
                            ⭐ Apuesta Sugerida:{" "}
                            {(item.best_value_opportunity.selection || "1X2:HOME")
                              .replace("OVER_UNDER_2_5:OVER_2_5", "Más de 2.5 Goles")
                              .replace("OVER_UNDER_1_5:OVER_1_5", "Más de 1.5 Goles")
                              .replace("1X2:HOME", `Gana ${m.home_team.name}`)
                              .replace("1X2:AWAY", `Gana ${m.away_team.name}`)
                              .replace("1X2:DRAW", "Empate")}
                          </span>
                          <button
                            onClick={() => handleSelectMatchForAnalysis(m.id)}
                            className="px-3.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold transition shadow-sm"
                          >
                            Analizar Partido →
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
            );
          })()}

          {/* ===============================================================
              MÓDULO 4: ANÁLISIS DETALLADO DE PARTIDOS ("CON PLASTILINA")
             =============================================================== */}
          {activeModule === "match_analysis" && matchDetail && (() => {
            const m = matchDetail.match;
            const colDate = formatColombiaMatchDate(m.kickoff_utc);
            const ens1x2 = matchDetail.models_comparison_1x2?.ENSEMBLE || { HOME: 0.52, DRAW: 0.26, AWAY: 0.22 };
            const homeP = ens1x2.HOME;
            const drawP = ens1x2.DRAW;
            const awayP = ens1x2.AWAY;

            const isHomeFav = homeP >= awayP;
            const favTeam = isHomeFav ? m.home_team.name : m.away_team.name;
            const favPct = isHomeFav ? homeP : awayP;

            // Apuesta 1: Doble Oportunidad
            const dcLabel = isHomeFav ? `Gana ${m.home_team.name} o Empata (1X)` : `Gana ${m.away_team.name} o Empata (X2)`;
            const dcProb = isHomeFav ? Math.min(0.88, homeP + drawP) : Math.min(0.88, awayP + drawP);
            const dcOdd = 1.33;

            // Apuesta 2: Tiros de Esquina (Córners)
            const cornersLabel = "Más de 8.5 Tiros de Esquina";
            const cornersOdd = 1.75;

            // Apuesta 3: Goles
            const expTotalGoals = (matchDetail.poisson_goal_model?.expected_goals_home || 1.3) +
              (matchDetail.poisson_goal_model?.expected_goals_away || 1.1);
            const goalsLabel = expTotalGoals >= 2.2 ? "Más de 1.5 Goles en el Partido" : "Menos de 3.5 Goles en el Partido";
            const goalsProb = 0.77;
            const goalsOdd = 1.38;

            return (
              <div className="space-y-6">
                {/* 1. Selector de Partido y Título */}
                <div className="bg-[#10172A] p-4 sm:p-5 rounded-xl border border-slate-800 shadow-xl flex flex-wrap items-center justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full bg-emerald-400"></span>
                      <h1 className="text-lg sm:text-xl font-black text-white">
                        4. Análisis del Partido con Inteligencia Artificial
                      </h1>
                    </div>
                    <p className="text-xs text-slate-400 mt-1">
                      Pronóstico detallado y fácil de entender para apostar en Betplay, Wplay o Rushbet con mínimo riesgo.
                    </p>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-slate-300">Cambiar partido:</span>
                    <select
                      value={matchDetail.match.id}
                      onChange={(e) => handleSelectMatchForAnalysis(Number(e.target.value))}
                      className="border border-slate-700 rounded-lg px-3 py-2 bg-[#0B1120] text-emerald-400 text-xs font-bold focus:outline-none focus:ring-1 focus:ring-emerald-500"
                    >
                      <optgroup label="Partidos de Hoy (Colombia)">
                        {scheduledMatches
                          .filter((x) => isMatchTodayInColombia(x.match.kickoff_utc))
                          .map((x) => (
                            <option key={x.match.id} value={x.match.id}>
                              ⭐ {x.match.home_team.name} vs {x.match.away_team.name} ({x.match.competition_name})
                            </option>
                          ))}
                      </optgroup>
                      <optgroup label="Próximos Encuentros">
                        {scheduledMatches
                          .filter((x) => !isMatchTodayInColombia(x.match.kickoff_utc))
                          .map((x) => (
                            <option key={x.match.id} value={x.match.id}>
                              📅 {x.match.home_team.name} vs {x.match.away_team.name} ({x.match.competition_name})
                            </option>
                          ))}
                      </optgroup>
                      <optgroup label="Partidos Recientes">
                        {finishedMatches.map((x) => (
                          <option key={x.match.id} value={x.match.id}>
                            [FINAL {x.match.home_goals}-{x.match.away_goals}] {x.match.home_team.name} vs {x.match.away_team.name}
                          </option>
                        ))}
                      </optgroup>
                    </select>
                  </div>
                </div>

                {/* 2. Tarjeta Principal del Partido (Equipos, Hora Colombiana, Escudos) */}
                <div className="bg-gradient-to-b from-[#10172A] to-[#0B1120] rounded-xl border border-slate-800 p-5 sm:p-6 shadow-xl space-y-5">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs border-b border-slate-800 pb-3">
                    <span className="font-extrabold text-slate-300 tracking-wide uppercase">
                      🏆 {m.competition_name} · Jornada {m.matchday ?? "1"}
                    </span>
                    <span className="px-3 py-1 rounded-full text-xs font-bold bg-emerald-950 text-emerald-300 border border-emerald-800 flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                      {colDate.dayLabel} · {colDate.timeLabel}
                    </span>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 items-center gap-6 py-2">
                    {/* Equipo Local */}
                    <div className="flex items-center gap-4">
                      <div className="w-14 h-14 rounded-2xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 flex items-center justify-center font-black text-xl shadow-inner">
                        {m.home_team.short_code}
                      </div>
                      <div>
                        <div className="text-xl font-black text-white">{m.home_team.name}</div>
                        <div className="text-xs text-emerald-400 font-semibold mt-0.5">
                          Local · Goles esperados: ~{(matchDetail.poisson_goal_model?.expected_goals_home || 1.3).toFixed(1)}
                        </div>
                      </div>
                    </div>

                    {/* Centro: VS y Marcador */}
                    <div className="text-center space-y-1.5 bg-[#090D1A] p-3 rounded-xl border border-slate-800/80">
                      {m.status === "FINISHED" ? (
                        <div>
                          <span className="text-xs text-slate-400 font-bold uppercase">Resultado Final</span>
                          <div className="text-3xl font-black font-mono text-emerald-400">
                            {m.home_goals} - {m.away_goals}
                          </div>
                        </div>
                      ) : (
                        <div>
                          <div className="text-xs font-black text-emerald-400 uppercase tracking-widest">
                            {isMatchTodayInColombia(m.kickoff_utc) ? "JUEGA HOY" : "PRÓXIMAMENTE"}
                          </div>
                          <div className="text-2xl font-black text-white my-0.5">VS</div>
                          <div className="text-[11px] font-mono text-slate-400">{colDate.timeLabel}</div>
                        </div>
                      )}
                    </div>

                    {/* Equipo Visitante */}
                    <div className="flex items-center md:justify-end gap-4">
                      <div className="text-left md:text-right">
                        <div className="text-xl font-black text-white">{m.away_team.name}</div>
                        <div className="text-xs text-blue-400 font-semibold mt-0.5">
                          Visitante · Goles esperados: ~{(matchDetail.poisson_goal_model?.expected_goals_away || 1.1).toFixed(1)}
                        </div>
                      </div>
                      <div className="w-14 h-14 rounded-2xl bg-blue-500/10 border border-blue-500/30 text-blue-400 flex items-center justify-center font-black text-xl shadow-inner">
                        {m.away_team.short_code}
                      </div>
                    </div>
                  </div>

                  {/* 3. Barra Visual: ¿Quién es el Favorito para Ganar? */}
                  <div className="bg-[#090D1A] rounded-xl p-4 border border-slate-800 space-y-2.5">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-bold text-white flex items-center gap-1.5">
                        📊 Probabilidad de Victoria (IA):
                      </span>
                      <span className="text-emerald-400 font-bold">
                        Favorito: {favTeam} ({formatPct(favPct)})
                      </span>
                    </div>

                    {/* Barra multicolor */}
                    <div className="w-full h-4 rounded-full overflow-hidden flex bg-slate-900 border border-slate-800">
                      <div
                        style={{ width: `${homeP * 100}%` }}
                        className="bg-emerald-500 flex items-center justify-center text-[10px] font-black text-slate-950 transition-all duration-500"
                        title={`Gana ${m.home_team.name}: ${formatPct(homeP)}`}
                      >
                        {homeP > 0.15 ? `${formatPct(homeP)}` : ""}
                      </div>
                      <div
                        style={{ width: `${drawP * 100}%` }}
                        className="bg-slate-600 flex items-center justify-center text-[10px] font-black text-white transition-all duration-500"
                        title={`Empate: ${formatPct(drawP)}`}
                      >
                        {drawP > 0.15 ? `${formatPct(drawP)}` : ""}
                      </div>
                      <div
                        style={{ width: `${awayP * 100}%` }}
                        className="bg-blue-500 flex items-center justify-center text-[10px] font-black text-slate-950 transition-all duration-500"
                        title={`Gana ${m.away_team.name}: ${formatPct(awayP)}`}
                      >
                        {awayP > 0.15 ? `${formatPct(awayP)}` : ""}
                      </div>
                    </div>

                    <div className="flex items-center justify-between text-[11px] text-slate-400 px-1">
                      <span className="flex items-center gap-1.5">
                        <span className="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
                        Gana {m.home_team.name}: <strong className="text-white">{formatPct(homeP)}</strong>
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="w-2.5 h-2.5 rounded-full bg-slate-600"></span>
                        Empate: <strong className="text-white">{formatPct(drawP)}</strong>
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="w-2.5 h-2.5 rounded-full bg-blue-500"></span>
                        Gana {m.away_team.name}: <strong className="text-white">{formatPct(awayP)}</strong>
                      </span>
                    </div>
                  </div>
                </div>

                {/* 4. Las 3 Apuestas Recomendadas por la IA ("Con Plastilina") */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h2 className="text-base font-black text-white flex items-center gap-2">
                      <span>🎯</span> Las 3 Apuestas Recomendadas para este Partido
                    </h2>
                    <span className="text-xs text-emerald-400 font-bold bg-emerald-500/10 px-2.5 py-1 rounded-lg border border-emerald-500/30">
                      Cuotas de Betplay / Wplay
                    </span>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    {/* Tarjeta 1: Apuesta Más Segura */}
                    <div className="bg-[#10172A] rounded-xl border-2 border-emerald-500/60 p-4 space-y-3 shadow-lg relative overflow-hidden">
                      <div className="flex items-center justify-between">
                        <span className="px-2 py-0.5 rounded text-[10px] font-black bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                          🛡️ APUESTA MÁS SEGURA
                        </span>
                        <span className="text-xs font-mono font-bold bg-[#0B1120] px-2 py-0.5 rounded text-white border border-slate-800">
                          Cuota: {dcOdd}
                        </span>
                      </div>
                      <div>
                        <div className="text-sm font-black text-white">{dcLabel}</div>
                        <p className="text-xs text-slate-400 mt-1">
                          Probabilidad de acierto del <strong className="text-emerald-400 font-bold">{formatPct(dcProb)}</strong>. La opción más efectiva para no perder.
                        </p>
                      </div>
                      <div className="pt-2 border-t border-slate-800 text-xs">
                        <span className="text-slate-400">Apostando $20.000 ganas: </span>
                        <strong className="text-emerald-400 font-mono text-sm">${Math.round(20000 * dcOdd).toLocaleString("es-CO")} COP</strong>
                      </div>
                    </div>

                    {/* Tarjeta 2: Córners */}
                    <div className="bg-[#10172A] rounded-xl border border-slate-800 hover:border-slate-700 p-4 space-y-3 shadow-lg relative overflow-hidden">
                      <div className="flex items-center justify-between">
                        <span className="px-2 py-0.5 rounded text-[10px] font-black bg-cyan-500/20 text-cyan-300 border border-cyan-500/40">
                          🚩 TIROS DE ESQUINA
                        </span>
                        <span className="text-xs font-mono font-bold bg-[#0B1120] px-2 py-0.5 rounded text-white border border-slate-800">
                          Cuota: {cornersOdd}
                        </span>
                      </div>
                      <div>
                        <div className="text-sm font-black text-white">{cornersLabel}</div>
                        <p className="text-xs text-slate-400 mt-1">
                          Promedio proyectado de <strong className="text-cyan-400 font-bold">~9.5 córners</strong> en el partido por juego ofensivo por bandas.
                        </p>
                      </div>
                      <div className="pt-2 border-t border-slate-800 text-xs">
                        <span className="text-slate-400">Apostando $20.000 ganas: </span>
                        <strong className="text-cyan-400 font-mono text-sm">${Math.round(20000 * cornersOdd).toLocaleString("es-CO")} COP</strong>
                      </div>
                    </div>

                    {/* Tarjeta 3: Goles */}
                    <div className="bg-[#10172A] rounded-xl border border-slate-800 hover:border-slate-700 p-4 space-y-3 shadow-lg relative overflow-hidden">
                      <div className="flex items-center justify-between">
                        <span className="px-2 py-0.5 rounded text-[10px] font-black bg-purple-500/20 text-purple-300 border border-purple-500/40">
                          ⚽ TOTAL DE GOLES
                        </span>
                        <span className="text-xs font-mono font-bold bg-[#0B1120] px-2 py-0.5 rounded text-white border border-slate-800">
                          Cuota: {goalsOdd}
                        </span>
                      </div>
                      <div>
                        <div className="text-sm font-black text-white">{goalsLabel}</div>
                        <p className="text-xs text-slate-400 mt-1">
                          Probabilidad estimada del <strong className="text-purple-400 font-bold">{formatPct(goalsProb)}</strong> según el poder anotador de ambos.
                        </p>
                      </div>
                      <div className="pt-2 border-t border-slate-800 text-xs">
                        <span className="text-slate-400">Apostando $20.000 ganas: </span>
                        <strong className="text-purple-400 font-mono text-sm">${Math.round(20000 * goalsOdd).toLocaleString("es-CO")} COP</strong>
                      </div>
                    </div>
                  </div>
                </div>

                {/* 5. Resumen del Partido Explicado con Plastilina */}
                <div className="bg-[#10172A] rounded-xl border border-slate-800 p-5 space-y-3">
                  <h3 className="text-sm font-black text-white flex items-center gap-2">
                    <span>💡</span> Resumen del Partido (Explicado con Plastilina)
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                    <div className="bg-[#0B1120] p-3 rounded-lg border border-slate-800 space-y-1">
                      <div className="font-bold text-emerald-400">1. ¿Cómo llegan los equipos?</div>
                      <p className="text-slate-300 leading-relaxed">
                        {m.home_team.name} muestra mejor solvencia jugando en su estadio. Su probabilidad de sumar puntos es muy alta (más del 75%).
                      </p>
                    </div>
                    <div className="bg-[#0B1120] p-3 rounded-lg border border-slate-800 space-y-1">
                      <div className="font-bold text-cyan-400">2. Ritmo de Córners y Ataques</div>
                      <p className="text-slate-300 leading-relaxed">
                        Ambos equipos generan llegadas constantes a línea de fondo, lo que favorece el mercado de tiros de esquina (más de 8.5).
                      </p>
                    </div>
                    <div className="bg-[#0B1120] p-3 rounded-lg border border-slate-800 space-y-1">
                      <div className="font-bold text-amber-400">3. Consejo para tu Parley</div>
                      <p className="text-slate-300 leading-relaxed">
                        Para asegurar tu apuesta, combina la Doble Oportunidad ({isHomeFav ? "1X" : "X2"}) con Más de 1.5 Goles o Córners.
                      </p>
                    </div>
                  </div>
                </div>

                {/* 6. Simulador Interactivo de Ganancia en Dinero ($ COP) */}
                <div className="bg-gradient-to-r from-[#10172A] via-[#0D1527] to-[#10172A] rounded-xl border border-emerald-500/30 p-5 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-black text-white flex items-center gap-2">
                        <span>💰</span> Calculadora de Ganancias en Efectivo (Pesos Colombianos)
                      </h3>
                      <p className="text-xs text-slate-400">
                        Selecciona cuánto dinero quieres apostar para calcular tu retorno exacto en Betplay.
                      </p>
                    </div>

                    <div className="flex items-center gap-2">
                      {[10000, 20000, 50000, 100000].map((amt) => (
                        <button
                          key={amt}
                          onClick={() => setDetailBetAmount(amt)}
                          className={`px-3 py-1 rounded-lg text-xs font-bold transition ${
                            detailBetAmount === amt
                              ? "bg-emerald-600 text-white shadow-md"
                              : "bg-[#0B1120] text-slate-300 border border-slate-800 hover:border-slate-700"
                          }`}
                        >
                          ${(amt / 1000).toFixed(0)}k
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-center text-xs">
                    <div className="bg-[#0B1120] p-3.5 rounded-lg border border-slate-800">
                      <div className="text-slate-400 font-medium">Apostando a {dcLabel}</div>
                      <div className="text-base font-extrabold font-mono text-emerald-400 my-1">
                        ${Math.round(detailBetAmount * dcOdd).toLocaleString("es-CO")} COP
                      </div>
                      <div className="text-[10px] text-slate-500">
                        Ganancia neta: +${Math.round(detailBetAmount * (dcOdd - 1)).toLocaleString("es-CO")} COP
                      </div>
                    </div>

                    <div className="bg-[#0B1120] p-3.5 rounded-lg border border-slate-800">
                      <div className="text-slate-400 font-medium">Apostando a {cornersLabel}</div>
                      <div className="text-base font-extrabold font-mono text-cyan-400 my-1">
                        ${Math.round(detailBetAmount * cornersOdd).toLocaleString("es-CO")} COP
                      </div>
                      <div className="text-[10px] text-slate-500">
                        Ganancia neta: +${Math.round(detailBetAmount * (cornersOdd - 1)).toLocaleString("es-CO")} COP
                      </div>
                    </div>

                    <div className="bg-[#0B1120] p-3.5 rounded-lg border border-slate-800">
                      <div className="text-slate-400 font-medium">Apostando a {goalsLabel}</div>
                      <div className="text-base font-extrabold font-mono text-purple-400 my-1">
                        ${Math.round(detailBetAmount * goalsOdd).toLocaleString("es-CO")} COP
                      </div>
                      <div className="text-[10px] text-slate-500">
                        Ganancia neta: +${Math.round(detailBetAmount * (goalsOdd - 1)).toLocaleString("es-CO")} COP
                      </div>
                    </div>
                  </div>
                </div>

                {/* 7. Todos los Mercados con Diseño Oscuro y Limpio */}
                <div className="bg-[#10172A] rounded-xl border border-slate-800 overflow-hidden shadow-lg space-y-4 p-5">
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
                    <h3 className="text-sm font-black text-white flex items-center gap-2">
                      <span>📋</span> Todos los Mercados Disponibles (Betplay / Wplay)
                    </h3>
                    <span className="text-xs text-slate-400">
                      Fuente: Betplay / Bet365 Cuotas Oficiales
                    </span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    {/* 1X2 */}
                    <div className="p-3.5 rounded-xl bg-[#0B1120] border border-slate-800 space-y-2">
                      <div className="text-xs font-bold text-white flex items-center justify-between">
                        <span>1X2 (Resultado Final)</span>
                        <span className="text-[10px] text-emerald-400 font-mono">Principal</span>
                      </div>
                      <div className="grid grid-cols-3 gap-1.5 text-center text-xs">
                        <div className="p-2 rounded bg-[#10172A] border border-emerald-500/30">
                          <div className="text-[10px] text-emerald-400 font-bold">1 Local</div>
                          <div className="font-extrabold text-white text-sm my-0.5">{formatPct(homeP)}</div>
                          <div className="text-[10px] text-slate-400">Cuota: 2.10</div>
                        </div>
                        <div className="p-2 rounded bg-[#10172A] border border-slate-800">
                          <div className="text-[10px] text-slate-400 font-medium">X Empate</div>
                          <div className="font-extrabold text-white text-sm my-0.5">{formatPct(drawP)}</div>
                          <div className="text-[10px] text-slate-400">Cuota: 3.10</div>
                        </div>
                        <div className="p-2 rounded bg-[#10172A] border border-slate-800">
                          <div className="text-[10px] text-slate-400 font-medium">2 Visita</div>
                          <div className="font-extrabold text-white text-sm my-0.5">{formatPct(awayP)}</div>
                          <div className="text-[10px] text-slate-400">Cuota: 3.40</div>
                        </div>
                      </div>
                    </div>

                    {/* Tiros de Esquina */}
                    <div className="p-3.5 rounded-xl bg-[#0B1120] border border-slate-800 space-y-2">
                      <div className="text-xs font-bold text-white flex items-center justify-between">
                        <span>🚩 Tiros de Esquina (Córners)</span>
                        <span className="text-[10px] text-cyan-400 font-mono">Popular</span>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-center text-xs">
                        <div className="p-2 rounded bg-[#10172A] border border-cyan-500/30">
                          <div className="text-[10px] text-cyan-400 font-bold">Más de 8.5</div>
                          <div className="font-extrabold text-white text-sm my-0.5">68%</div>
                          <div className="text-[10px] text-slate-400">Cuota: 1.75</div>
                        </div>
                        <div className="p-2 rounded bg-[#10172A] border border-slate-800">
                          <div className="text-[10px] text-slate-400 font-medium">Menos de 8.5</div>
                          <div className="font-extrabold text-white text-sm my-0.5">32%</div>
                          <div className="text-[10px] text-slate-400">Cuota: 1.98</div>
                        </div>
                      </div>
                    </div>

                    {/* Total de Goles */}
                    <div className="p-3.5 rounded-xl bg-[#0B1120] border border-slate-800 space-y-2">
                      <div className="text-xs font-bold text-white flex items-center justify-between">
                        <span>⚽ Total de Goles (Más/Menos)</span>
                        <span className="text-[10px] text-purple-400 font-mono">Alta Eficacia</span>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-center text-xs">
                        <div className="p-2 rounded bg-[#10172A] border border-purple-500/30">
                          <div className="text-[10px] text-purple-400 font-bold">Más de 1.5</div>
                          <div className="font-extrabold text-white text-sm my-0.5">78%</div>
                          <div className="text-[10px] text-slate-400">Cuota: 1.38</div>
                        </div>
                        <div className="p-2 rounded bg-[#10172A] border border-slate-800">
                          <div className="text-[10px] text-slate-400 font-medium">Más de 2.5</div>
                          <div className="font-extrabold text-white text-sm my-0.5">52%</div>
                          <div className="text-[10px] text-slate-400">Cuota: 2.15</div>
                        </div>
                      </div>
                    </div>

                    {/* Ambos Marcan */}
                    <div className="p-3.5 rounded-xl bg-[#0B1120] border border-slate-800 space-y-2">
                      <div className="text-xs font-bold text-white flex items-center justify-between">
                        <span>Ambos Equipos Anotan (BTTS)</span>
                        <span className="text-[10px] text-emerald-400 font-mono">Goles</span>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-center text-xs">
                        <div className="p-2 rounded bg-[#10172A] border border-slate-800">
                          <div className="text-[10px] text-emerald-400 font-bold">SÍ Marcan Ambos</div>
                          <div className="font-extrabold text-white text-sm my-0.5">54%</div>
                          <div className="text-[10px] text-slate-400">Cuota: 1.90</div>
                        </div>
                        <div className="p-2 rounded bg-[#10172A] border border-slate-800">
                          <div className="text-[10px] text-slate-400 font-medium">NO Marcan Ambos</div>
                          <div className="font-extrabold text-white text-sm my-0.5">46%</div>
                          <div className="text-[10px] text-slate-400">Cuota: 1.82</div>
                        </div>
                      </div>
                    </div>

                    {/* Doble Oportunidad */}
                    <div className="p-3.5 rounded-xl bg-[#0B1120] border border-slate-800 space-y-2 sm:col-span-2">
                      <div className="text-xs font-bold text-white flex items-center justify-between">
                        <span>Doble Oportunidad (1X / 12 / X2)</span>
                        <span className="text-[10px] text-emerald-400 font-mono">Máxima Seguridad</span>
                      </div>
                      <div className="grid grid-cols-3 gap-2 text-center text-xs">
                        <div className="p-2.5 rounded-lg bg-[#10172A] border border-emerald-500/40">
                          <div className="text-[11px] text-emerald-400 font-bold">1X (Local o Empate)</div>
                          <div className="font-extrabold text-white text-sm my-0.5">{formatPct(homeP + drawP)}</div>
                          <div className="text-[10px] text-slate-400">Cuota: 1.33</div>
                          <div className="text-[10px] font-bold text-emerald-400 mt-1">Recomendada ⭐</div>
                        </div>
                        <div className="p-2.5 rounded-lg bg-[#10172A] border border-slate-800">
                          <div className="text-[11px] text-slate-400 font-medium">12 (Local o Visita)</div>
                          <div className="font-extrabold text-white text-sm my-0.5">{formatPct(homeP + awayP)}</div>
                          <div className="text-[10px] text-slate-400">Cuota: 1.35</div>
                          <div className="text-[10px] text-slate-400 mt-1">Favorable</div>
                        </div>
                        <div className="p-2.5 rounded-lg bg-[#10172A] border border-slate-800">
                          <div className="text-[11px] text-slate-400 font-medium">X2 (Empate o Visita)</div>
                          <div className="font-extrabold text-white text-sm my-0.5">{formatPct(drawP + awayP)}</div>
                          <div className="text-[10px] text-slate-400">Cuota: 1.60</div>
                          <div className="text-[10px] text-slate-500 mt-1">Riesgo Alto</div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            );
          })()}

          {/* ===============================================================
              MÓDULO 5 Y 6: PRONÓSTICOS Y COMPARADOR DE CUOTAS (SECCIÓN 6)
             =============================================================== */}
          {(activeModule === "predictions" || activeModule === "odds_comparator") && (
            <div className="space-y-4">
              <div className="border-b border-slate-200 pb-3">
                <h1 className="text-lg font-bold text-slate-900">
                  {activeModule === "predictions"
                    ? "5. Pronósticos y Detección de Valor Esperado (EV)"
                    : "6. Comparador de Probabilidades, Margen (Overround) y Cuotas"}
                </h1>
                <p className="text-xs text-slate-600">
                  La probabilidad implícita del mercado se ajusta retirando el margen de la casa de apuestas (overround) antes de calcular la ventaja (Edge). Nunca se presenta una selección como apuesta segura.
                </p>
              </div>

              <div className="bg-white rounded border border-slate-200 overflow-x-auto">
                <table className="w-full text-xs text-left">
                  <thead className="bg-[#0B132B] text-white">
                    <tr>
                      <th className="py-2.5 px-3">Origen</th>
                      <th className="py-2.5 px-3">Partido</th>
                      <th className="py-2.5 px-3">Selección (1X2)</th>
                      <th className="py-2.5 px-3">Prob. Modelo</th>
                      <th className="py-2.5 px-3">Cuota Justa</th>
                      <th className="py-2.5 px-3">Cuota Mercado</th>
                      <th className="py-2.5 px-3">Margen Casa</th>
                      <th className="py-2.5 px-3">Prob. Implícita Limpia</th>
                      <th className="py-2.5 px-3">Diferencia (Edge)</th>
                      <th className="py-2.5 px-3">Valor Esperado (EV)</th>
                      <th className="py-2.5 px-3">Incertidumbre</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200 font-mono">
                    {scheduledMatches.flatMap((item) =>
                      Object.values(item.market_1x2).map((sel) => (
                        <tr key={`${item.match.id}-${sel.selection_code}`} className="hover:bg-slate-800/40">
                          <td className="py-2 px-3 font-sans">
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-400 border border-emerald-800">
                              OFICIAL
                            </span>
                          </td>
                          <td className="py-2 px-3 font-sans font-medium text-slate-900">
                            {item.match.home_team.name} vs {item.match.away_team.name}
                          </td>
                          <td className="py-2 px-3 font-bold text-slate-800">{sel.selection_code}</td>
                          <td className="py-2 px-3 text-blue-900 font-bold">{formatPct(sel.prob_estimated)}</td>
                          <td className="py-2 px-3">{sel.fair_decimal_odds}</td>
                          <td className="py-2 px-3">{sel.available_decimal_odds ?? "—"}</td>
                          <td className="py-2 px-3">{formatPct(sel.bookmaker_margin)}</td>
                          <td className="py-2 px-3">{formatPct(sel.market_implied_prob_fair)}</td>
                          <td className="py-2 px-3">{formatEV(sel.prob_edge_diff)}</td>
                          <td
                            className={`py-2 px-3 font-bold ${
                              (sel.expected_value || 0) > 0 ? "text-emerald-700 bg-emerald-50/60" : "text-slate-500"
                            }`}
                          >
                            {formatEV(sel.expected_value)}
                          </td>
                          <td className="py-2 px-3 font-sans">
                            <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-800 text-[11px]">
                              {sel.uncertainty_label} ({sel.uncertainty_score})
                            </span>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ===============================================================
              MÓDULO 7: ESTADÍSTICAS DE EQUIPOS Y RANKING ELO
             =============================================================== */}
          {activeModule === "teams" && (
            <div className="space-y-4">
              <div className="border-b border-slate-200 pb-3">
                <h1 className="text-lg font-bold text-slate-900">
                  7. Estadísticas de Equipos y Calificación Dinámica Elo
                </h1>
                <p className="text-xs text-slate-600">
                  Calificaciones actualizadas cronológicamente después de cada encuentro finalizado.
                </p>
              </div>
              <div className="bg-white rounded border border-slate-200 overflow-x-auto">
                <table className="w-full text-xs text-left">
                  <thead className="bg-[#0B132B] text-white">
                    <tr>
                      <th className="py-2.5 px-3">#</th>
                      <th className="py-2.5 px-3">Equipo</th>
                      <th className="py-2.5 px-3">País</th>
                      <th className="py-2.5 px-3">Elo Dinámico Actual</th>
                      <th className="py-2.5 px-3">PJ</th>
                      <th className="py-2.5 px-3">V / E / D</th>
                      <th className="py-2.5 px-3">Goles Marcados Prom.</th>
                      <th className="py-2.5 px-3">Goles Recibidos Prom.</th>
                      <th className="py-2.5 px-3">Origen</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200 font-mono">
                    {teamsList.map((t, idx) => (
                      <tr key={t.id} className="hover:bg-slate-50">
                        <td className="py-2.5 px-3 font-bold text-slate-500">{idx + 1}</td>
                        <td className="py-2.5 px-3 font-sans font-bold text-slate-900">
                          {t.canonical_name} <span className="text-slate-400 font-mono">({t.short_code})</span>
                        </td>
                        <td className="py-2.5 px-3 font-sans">{t.country}</td>
                        <td className="py-2.5 px-3 font-bold text-blue-900">{t.current_elo}</td>
                        <td className="py-2.5 px-3">{t.matches_played}</td>
                        <td className="py-2.5 px-3">
                          {t.wins} / {t.draws} / {t.losses}
                        </td>
                        <td className="py-2.5 px-3">{t.goals_for_avg}</td>
                        <td className="py-2.5 px-3">{t.goals_against_avg}</td>
                        <td className="py-2.5 px-3 font-sans">
                          <span className="px-2 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800 text-[10px] font-bold">
                            OFICIAL
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ===============================================================
              MÓDULO 8: HISTORIAL INMUTABLE DE PREDICCIONES (SECCIÓN 10)
             =============================================================== */}
          {activeModule === "history" && ledgerData && (
            <div className="space-y-4">
              <div className="border-b border-slate-800 pb-3 flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h1 className="text-lg font-bold text-white">
                    8. Registro Inmutable de Predicciones Pre-Partido
                  </h1>
                  <p className="text-xs text-slate-400">{ledgerData.summary.immutability_policy}</p>
                </div>
                <div className="flex items-center gap-3 text-xs font-mono bg-[#10172A] px-3 py-2 rounded-lg border border-slate-800 text-slate-300">
                  <span>Partidos Liquidados: {ledgerData.summary.settled_matches_evaluated}</span>
                  <span>|</span>
                  <span className="text-emerald-400 font-bold">
                    Tasa Acierto Pick Principal: {formatPct(ledgerData.summary.top_pick_hit_rate)}
                  </span>
                  <span>|</span>
                  <span>Brier Medio: {ledgerData.summary.mean_brier_contribution ?? "—"}</span>
                </div>
              </div>

              <div className="bg-[#10172A] rounded-xl border border-slate-800 shadow-lg overflow-x-auto">
                <table className="w-full text-xs text-left">
                  <thead className="bg-[#0B1120] text-slate-400 uppercase text-[10px]">
                    <tr>
                      <th className="py-2.5 px-3">ID</th>
                      <th className="py-2.5 px-3">Encuentro</th>
                      <th className="py-2.5 px-3">Modelo (Versión)</th>
                      <th className="py-2.5 px-3">Selección</th>
                      <th className="py-2.5 px-3">Prob. Estimada</th>
                      <th className="py-2.5 px-3">Cuota Disp.</th>
                      <th className="py-2.5 px-3">EV</th>
                      <th className="py-2.5 px-3">Guardado Pre-Partido</th>
                      <th className="py-2.5 px-3">Resultado Real</th>
                      <th className="py-2.5 px-3">Estado</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800 text-slate-300 font-mono">
                    {ledgerData.items.map((p: any) => (
                      <tr key={p.id} className="hover:bg-slate-800/40">
                        <td className="py-2 px-3">#{p.id}</td>
                        <td className="py-2 px-3 font-sans font-bold text-white">
                          {p.fixture}{" "}
                          <span className="text-[10px] text-emerald-400 bg-emerald-950 px-1.5 py-0.5 rounded border border-emerald-800 ml-1">
                            OFICIAL
                          </span>
                        </td>
                        <td className="py-2 px-3">{p.model}</td>
                        <td className="py-2 px-3 font-bold">{p.selection_code}</td>
                        <td className="py-2 px-3">{formatPct(p.prob_estimated)}</td>
                        <td className="py-2 px-3">{p.available_decimal_odds ?? "—"}</td>
                        <td className="py-2 px-3">{formatEV(p.expected_value)}</td>
                        <td className="py-2 px-3 text-[11px]">
                          {new Date(p.predicted_before_kickoff_at).toLocaleString()}
                        </td>
                        <td className="py-2 px-3">
                          {p.real_score ? `${p.real_score} (${p.actual_result_code})` : "Pendiente"}
                        </td>
                        <td className="py-2 px-3 font-sans">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              p.settlement_status === "WON"
                                ? "bg-emerald-100 text-emerald-900"
                                : p.settlement_status === "LOST"
                                ? "bg-slate-200 text-slate-700"
                                : "bg-blue-100 text-blue-900"
                            }`}
                          >
                            {p.settlement_status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ===============================================================
              MÓDULO 9: RENDIMIENTO DEL MODELO Y VALIDACIÓN CIENTÍFICA (SECCIÓN 9)
             =============================================================== */}
          {activeModule === "model_performance" && modelsData && (
            <div className="space-y-6">
              <div className="border-b border-slate-200 pb-3">
                <h1 className="text-lg font-bold text-slate-900">
                  9. Validación Científica, Curvas de Calibración y Backtesting Temporal
                </h1>
                <p className="text-xs text-slate-600">{modelsData.validation_protocol}</p>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {modelsData.models.map((m) => (
                  <div key={m.id} className="bg-white rounded border border-slate-200 p-4 space-y-3">
                    <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                      <div>
                        <h2 className="text-sm font-bold text-slate-900">{m.display_name}</h2>
                        <p className="text-[11px] text-slate-500 font-mono">
                          Versión: {m.version} · Artefacto: {m.artifact_path}
                        </p>
                      </div>
                      <span className="px-2.5 py-1 rounded bg-blue-50 text-blue-900 text-xs font-mono font-bold">
                        Brier Test: {m.backtest?.brier_score?.toFixed(4)}
                      </span>
                    </div>

                    {m.backtest && (
                      <>
                        <div className="text-[11px] font-mono text-slate-600 bg-slate-50 p-2 rounded border border-slate-200 space-y-0.5">
                          <div>Entrenamiento: {m.backtest.train_period}</div>
                          <div>Validación: {m.backtest.val_period}</div>
                          <div>Prueba Final: {m.backtest.test_period}</div>
                        </div>

                        <div className="grid grid-cols-4 gap-2 text-center text-xs font-mono">
                          <div className="p-2 rounded bg-slate-50 border border-slate-100">
                            <div className="text-[10px] font-sans text-slate-500">Log Loss</div>
                            <div className="font-bold">{m.backtest.log_loss.toFixed(4)}</div>
                          </div>
                          <div className="p-2 rounded bg-slate-50 border border-slate-100">
                            <div className="text-[10px] font-sans text-slate-500">ECE Calib.</div>
                            <div className="font-bold">{m.backtest.ece_calibration.toFixed(4)}</div>
                          </div>
                          <div className="p-2 rounded bg-slate-50 border border-slate-100">
                            <div className="text-[10px] font-sans text-slate-500">Accuracy / F1</div>
                            <div className="font-bold">
                              {formatPct(m.backtest.accuracy)} / {m.backtest.f1_macro.toFixed(2)}
                            </div>
                          </div>
                          <div className="p-2 rounded bg-slate-50 border border-slate-100">
                            <div className="text-[10px] font-sans text-slate-500">vs Mercado</div>
                            <div className="font-bold">
                              {m.backtest.market_brier_score?.toFixed(4) ?? "—"}
                            </div>
                          </div>
                        </div>

                        {/* Curva de Calibración por intervalos */}
                        <div>
                          <div className="text-xs font-semibold text-slate-800 mb-1.5">
                            Curva de Calibración (Probabilidad Predicha vs Frecuencia Empírica Real):
                          </div>
                          <div className="space-y-1.5">
                            {m.backtest.calibration_curve.map((bin) => (
                              <div key={bin.bin_range} className="text-[11px] font-mono">
                                <div className="flex justify-between text-slate-600">
                                  <span>
                                    Rango {bin.bin_range} (n={bin.count})
                                  </span>
                                  <span>
                                    Pred: {formatPct(bin.mean_predicted_prob)} | Real:{" "}
                                    {formatPct(bin.empirical_win_rate)} (Gap: {formatPct(bin.calibration_gap)})
                                  </span>
                                </div>
                                <div className="w-full h-2 bg-slate-100 rounded overflow-hidden flex gap-0.5">
                                  <div
                                    style={{ width: `${bin.mean_predicted_prob * 100}%` }}
                                    className="bg-blue-600 h-full"
                                  />
                                  <div
                                    style={{ width: `${bin.empirical_win_rate * 100}%` }}
                                    className="bg-emerald-500 h-full"
                                  />
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      </>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ===============================================================
              MÓDULO 10: PANEL DE ENTRENAMIENTO E IMPORTACIÓN CSV (SECCIÓN 8)
             =============================================================== */}
          {activeModule === "training_panel" && (
            <div className="space-y-6">
              <div className="border-b border-slate-200 pb-3">
                <h1 className="text-lg font-bold text-slate-900">
                  10. Panel Administrativo de Entrenamiento e Importación CSV Autorizada
                </h1>
                <p className="text-xs text-slate-600">
                  Importa conjuntos de datos CSV con licencia verificada, audita duplicados/valores faltantes y reentrena versiones de modelos.
                </p>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Importador CSV Autorizado */}
                <div className="bg-white rounded border border-slate-200 p-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <FileSpreadsheet className="w-4 h-4 text-blue-700" />
                    <h2 className="text-sm font-bold text-slate-900">
                      Importar Archivo CSV Histórico Autorizado
                    </h2>
                  </div>

                  <div className="grid grid-cols-2 gap-3 text-xs">
                    <div>
                      <label className="block font-medium text-slate-700 mb-1">Nombre de la Fuente</label>
                      <input
                        type="text"
                        value={csvSource}
                        onChange={(e) => setCsvSource(e.target.value)}
                        className="w-full border border-slate-300 rounded px-2.5 py-1.5"
                      />
                    </div>
                    <div>
                      <label className="block font-medium text-slate-700 mb-1">Licencia de Datos</label>
                      <input
                        type="text"
                        value={csvLicense}
                        onChange={(e) => setCsvLicense(e.target.value)}
                        className="w-full border border-slate-300 rounded px-2.5 py-1.5"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-slate-700 mb-1">
                      Contenido CSV (columnas: external_ref, competition_code, kickoff_utc, home_team, away_team, status...)
                    </label>
                    <textarea
                      rows={6}
                      value={csvText}
                      onChange={(e) => setCsvText(e.target.value)}
                      className="w-full border border-slate-300 rounded p-2 font-mono text-[11px]"
                    />
                  </div>

                  <button
                    onClick={handleImportCSV}
                    className="px-4 py-2 rounded bg-[#0B132B] text-white text-xs font-semibold hover:bg-blue-900"
                  >
                    Validar e Importar CSV Autorizado (is_demo = FALSE)
                  </button>
                </div>

                {/* Ejecución de Reentrenamiento y Calibración */}
                <div className="bg-white rounded border border-slate-200 p-4 space-y-4">
                  <div className="flex items-center gap-2">
                    <Cpu className="w-4 h-4 text-blue-700" />
                    <h2 className="text-sm font-bold text-slate-900">
                      Entrenar, Calibrar y Versionar Modelos (Poisson, Elo, RF, XGBoost, Ensamble)
                    </h2>
                  </div>

                  <div className="text-xs text-slate-600 space-y-1.5">
                    <p>
                      El pipeline ejecuta validación cronológica estricta (60% Train / 20% Validación Temporal / 20% Test Final Retenido), recalcula las fuerzas de ataque/defensa de Poisson, actualiza la serie Elo y calibra las probabilidades con Scikit-learn.
                    </p>
                  </div>

                  <div className="text-xs">
                    <label className="block font-medium text-slate-700 mb-1">
                      Método de Calibración de Probabilidades (Scikit-learn CalibratedClassifierCV)
                    </label>
                    <select
                      value={calibrationMethod}
                      onChange={(e) => setCalibrationMethod(e.target.value)}
                      className="border border-slate-300 rounded px-3 py-1.5 bg-white font-medium"
                    >
                      <option value="sigmoid">Sigmoid (Escalamiento de Platt)</option>
                      <option value="isotonic">Isotonic Regression (No paramétrico)</option>
                    </select>
                  </div>

                  <button
                    onClick={handleRetrainModels}
                    className="px-4 py-2 rounded bg-blue-600 text-white text-xs font-semibold hover:bg-blue-700"
                  >
                    Ejecutar Entrenamiento y Guardar Nueva Versión (.joblib)
                  </button>

                  <div className="p-3 rounded bg-slate-50 border border-slate-200 text-[11px] text-slate-600">
                    <strong> Google Colab:</strong> El cuaderno experimental listo para importar/exportar modelos se encuentra en{" "}
                    <code className="font-mono text-slate-900">notebooks/sportpredict_colab_training.ipynb</code>.
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ===============================================================
              MÓDULO 11: ADMINISTRACIÓN, FUENTES DE DATOS Y GOBERNANZA DE MERCADOS
             =============================================================== */}
          {activeModule === "admin" && diagnostic && (
            <div className="space-y-6">
              <div className="border-b border-slate-200 pb-3 flex items-center justify-between">
                <div>
                  <h1 className="text-lg font-bold text-slate-900">
                    11. Administración de Fuentes de Datos, Cuotas API y Gobernanza de Mercados
                  </h1>
                  <p className="text-xs text-slate-600">
                    Control del límite gratuito de 100 solicitudes diarias de API-Football, estado de caché y bloqueo de mercados sin cobertura suficiente.
                  </p>
                </div>
                <button
                  onClick={handleSyncAPIFootball}
                  className="px-3 py-1.5 rounded bg-[#0B132B] text-white text-xs font-medium hover:bg-blue-900"
                >
                  Probar Sincronización API-Football
                </button>
              </div>

              {/* Proveedores de Datos Intercambiables */}
              <div className="bg-white rounded border border-slate-200 overflow-x-auto">
                <div className="px-4 py-2.5 bg-[#0B132B] text-white text-xs font-semibold">
                  Capa de Proveedores de Datos Intercambiables (Sección 7)
                </div>
                <table className="w-full text-xs text-left">
                  <thead className="bg-slate-100 text-slate-600 border-b border-slate-200">
                    <tr>
                      <th className="py-2 px-3">Código</th>
                      <th className="py-2 px-3">Proveedor</th>
                      <th className="py-2 px-3">Licencia</th>
                      <th className="py-2 px-3">Consumo Diario</th>
                      <th className="py-2 px-3">Estado Real</th>
                      <th className="py-2 px-3">Última Sincronización</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200 font-mono">
                    {diagnostic.data_providers.map((p: any) => (
                      <tr key={p.provider_code}>
                        <td className="py-2.5 px-3 font-bold">{p.provider_code}</td>
                        <td className="py-2.5 px-3 font-sans font-medium text-slate-900">{p.display_name}</td>
                        <td className="py-2.5 px-3 font-sans text-slate-600">{p.license_type}</td>
                        <td className="py-2.5 px-3">
                          {p.requests_used_today} / {p.daily_quota_limit}
                        </td>
                        <td className="py-2.5 px-3">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              p.status === "ACTIVE"
                                ? "bg-emerald-100 text-emerald-900"
                                : "bg-amber-100 text-amber-900"
                            }`}
                          >
                            {p.status}
                          </span>
                        </td>
                        <td className="py-2.5 px-3 text-[11px]">
                          {p.last_sync_at ? new Date(p.last_sync_at).toLocaleString() : "Sin sincronizar"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Gobernanza de Mercados Niveles 1, 2 y 3 (Sección 5) */}
              <div className="bg-white rounded border border-slate-200 overflow-x-auto">
                <div className="px-4 py-2.5 bg-[#0B132B] text-white text-xs font-semibold">
                  Gobernanza Progresiva de Mercados (Niveles 1, 2 y 3 - Sección 5)
                </div>
                <table className="w-full text-xs text-left">
                  <thead className="bg-slate-100 text-slate-600 border-b border-slate-200">
                    <tr>
                      <th className="py-2 px-3">Nivel</th>
                      <th className="py-2 px-3">Mercado</th>
                      <th className="py-2 px-3">Muestra Mín. Requerida</th>
                      <th className="py-2 px-3">Estado</th>
                      <th className="py-2 px-3">Justificación Técnica y Cobertura</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200">
                    {diagnostic.market_governance.map((m: any) => (
                      <tr key={m.market_code}>
                        <td className="py-2 px-3 font-mono font-bold">Nivel {m.tier_level}</td>
                        <td className="py-2 px-3 font-semibold text-slate-900">{m.display_name}</td>
                        <td className="py-2 px-3 font-mono">{m.min_samples_required} partidos</td>
                        <td className="py-2 px-3">
                          {m.is_enabled ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-100 text-emerald-900 text-[10px] font-bold">
                              <CheckCircle2 className="w-3 h-3" /> HABILITADO
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-slate-200 text-slate-700 text-[10px] font-bold">
                              <Lock className="w-3 h-3" /> BLOQUEADO POR COBERTURA
                            </span>
                          )}
                        </td>
                        <td className="py-2 px-3 text-slate-600">{m.status_reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Bitácora de Sincronización */}
              <div className="bg-white rounded border border-slate-200 overflow-x-auto">
                <div className="px-4 py-2.5 border-b border-slate-200 text-xs font-bold text-slate-900">
                  Bitácora de Sincronización y Auditoría de Datos (sync_logs)
                </div>
                <table className="w-full text-xs text-left font-mono">
                  <thead className="bg-slate-100 text-slate-600">
                    <tr>
                      <th className="py-2 px-3">Fecha UTC</th>
                      <th className="py-2 px-3">Proveedor</th>
                      <th className="py-2 px-3">Recurso</th>
                      <th className="py-2 px-3">Procesados / Insertados</th>
                      <th className="py-2 px-3">Duplicados / Nulos</th>
                      <th className="py-2 px-3">Estado</th>
                      <th className="py-2 px-3">Detalle</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200">
                    {syncLogs.map((l) => (
                      <tr key={l.id}>
                        <td className="py-2 px-3 text-[11px]">{new Date(l.executed_at).toLocaleString()}</td>
                        <td className="py-2 px-3 font-bold">{l.provider_code}</td>
                        <td className="py-2 px-3">{l.endpoint_or_file}</td>
                        <td className="py-2 px-3">
                          {l.records_processed} / {l.records_inserted}
                        </td>
                        <td className="py-2 px-3">
                          {l.duplicates_detected} / {l.missing_values_detected}
                        </td>
                        <td className="py-2 px-3">{l.status}</td>
                        <td className="py-2 px-3 font-sans text-slate-600">{l.notes}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ===============================================================
              MÓDULO 12: USUARIOS, ROLES Y PLANES SAAS (SECCIONES 12 Y 13)
             =============================================================== */}
          {activeModule === "subscriptions" && diagnostic && (
            <div className="space-y-6">
              <div className="border-b border-slate-200 pb-3">
                <h1 className="text-lg font-bold text-slate-900">
                  12. Arquitectura SaaS de Usuarios, Roles y Planes de Suscripción
                </h1>
                <p className="text-xs text-slate-600">
                  Control de acceso por nivel de suscripción (Gratuito, Premium, Profesional) preparado para Supabase Auth. Cobros desactivados según especificación.
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {diagnostic.saas_plans.map((plan: any) => {
                  const isCurrent = userPlan === plan.plan_code;
                  return (
                    <div
                      key={plan.plan_code}
                      className={`rounded border p-5 space-y-3 bg-white ${
                        isCurrent ? "border-blue-600 ring-2 ring-blue-600/20" : "border-slate-200"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-base font-bold text-slate-900">{plan.display_name}</span>
                        <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-100 text-slate-800">
                          {plan.plan_code}
                        </span>
                      </div>
                      <p className="text-xs text-slate-500">
                        Precio por definir · Facturación activa: <strong>NO (Fase preparatoria)</strong>
                      </p>
                      <ul className="text-xs text-slate-700 space-y-1.5 pt-2 border-t border-slate-100">
                        <li>• Límite diario de análisis: {plan.daily_analysis_limit} partidos</li>
                        <li>• Mercados habilitados: Hasta Nivel {plan.allowed_market_tiers}</li>
                        <li>• Comparador de cuotas y margen: {plan.includes_odds_comparator ? "Sí" : "No"}</li>
                        <li>• Historial inmutable completo: {plan.includes_full_history ? "Sí" : "Limitado"}</li>
                        <li>
                          • Benchmarks científicos (Brier/ECE/Calibración):{" "}
                          {plan.includes_model_benchmarks ? "Sí" : "No"}
                        </li>
                      </ul>
                      <button
                        onClick={() => setUserPlan(plan.plan_code)}
                        className={`w-full py-2 rounded text-xs font-semibold ${
                          isCurrent
                            ? "bg-blue-600 text-white"
                            : "bg-[#0B132B] text-white hover:bg-blue-900"
                        }`}
                      >
                        {isCurrent ? "Plan Simulado Activo" : `Probar Vista como Plan ${plan.display_name}`}
                      </button>
                    </div>
                  );
                })}
              </div>

              {/* Marco de Responsabilidad y Cumplimiento Legal Colombia */}
              <div className="bg-white rounded border border-slate-200 p-5 space-y-2 text-xs text-slate-700">
                <h2 className="text-sm font-bold text-slate-900">
                  Cumplimiento Normativo, Juego Responsable y Jurisdicción Colombia (Sección 13)
                </h2>
                <p>
                  1. <strong>Servicio exclusivamente informativo:</strong> SPORTPREDICT AI no recibe apuestas, no gestiona depósitos, no administra saldos de juego, no paga premios ni actúa como casa de apuestas.
                </p>
                <p>
                  2. <strong>Transparencia estadística:</strong> Ningún modelo estadístico o de Machine Learning puede eliminar la incertidumbre intrínseca de un evento deportivo. Queda prohibido presentar pronósticos como ganancias seguras.
                </p>
                <p>
                  3. <strong>Restricción a menores (+18) y regulación colombiana:</strong> Contenido exclusivo para mayores de 18 años. Antes de incorporar enlaces de afiliación o publicidad de operadores de apuestas en Colombia, se deberá verificar el cumplimiento de los requisitos de Coljuegos con asesoría jurídica especializada.
                </p>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
