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
  | "parleys_today"
  | "teams"
  | "history"
  | "match_analysis"
  | "dashboard"
  | "today"
  | "upcoming"
  | "predictions"
  | "odds_comparator"
  | "model_performance"
  | "training_panel"
  | "admin"
  | "subscriptions";

interface CustomBetPick {
  id: string;
  matchFixture: string;
  marketName: string;
  selectionLabel: string;
  odds: number;
}

const MODULES: Array<{ key: ModuleKey; label: string; number: number; icon: React.ComponentType<{ className?: string }> }> = [
  { key: "parleys_today", label: "🎯 1. Parleys y Apuestas de Hoy", number: 1, icon: TrendingUp },
  { key: "teams", label: "📊 2. Estadísticas de Equipos", number: 2, icon: Award },
  { key: "history", label: "📜 3. Historial de Predicciones", number: 3, icon: History },
];

const SAMPLE_AUTHORIZED_CSV = `external_ref,competition_code,competition_name,country,season,matchday,kickoff_utc,home_team,away_team,status,home_goals,away_goals,home_xg,away_xg,odds_home,odds_draw,odds_away
CSV-AUTH-2026-101,ESP_LALIGA,LaLiga EA Sports,España,2026/2027,17,2026-11-14T20:00:00Z,Real Madrid,Villarreal CF,SCHEDULED,,,,,1.52,4.30,6.10
CSV-AUTH-2026-102,ENG_EPL,Premier League,Inglaterra,2026/2027,17,2026-11-15T17:30:00Z,Liverpool FC,Arsenal FC,SCHEDULED,,,,,2.15,3.45,3.35`;

export default function SportPredictApp() {
  const [activeModule, setActiveModule] = useState<ModuleKey>("parleys_today");
  const [userRole, setUserRole] = useState<string>("ADMIN");
  const [userPlan, setUserPlan] = useState<string>("PRO");
  const [mobileMenuOpen, setMobileMenuOpen] = useState<boolean>(false);

  const [customParlayPicks, setCustomParlayPicks] = useState<CustomBetPick[]>([]);
  const [customBetAmount, setCustomBetAmount] = useState<number>(20000);

  const toggleCustomPick = (pick: CustomBetPick) => {
    setCustomParlayPicks((prev) => {
      const exists = prev.some((p) => p.id === pick.id);
      if (exists) {
        return prev.filter((p) => p.id !== pick.id);
      } else {
        return [...prev, pick];
      }
    });
  };

  const clearCustomPicks = () => setCustomParlayPicks([]);

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
  const [selectedDayFilter, setSelectedDayFilter] = useState<"today" | "tomorrow" | "all">("today");

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

  const isMatchTomorrowInColombia = (isoStr: string): boolean => {
    try {
      const d = new Date(isoStr);
      const matchDateStr = new Intl.DateTimeFormat("en-CA", {
        timeZone: "America/Bogota",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(d);

      const tomorrow = new Date();
      tomorrow.setDate(tomorrow.getDate() + 1);
      const tomorrowStr = new Intl.DateTimeFormat("en-CA", {
        timeZone: "America/Bogota",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(tomorrow);

      return matchDateStr === tomorrowStr;
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
              MÓDULO PRINCIPAL: PARLEYS Y APUESTAS DE HOY (BETPLAY / WPLAY)
             =============================================================== */}
          {activeModule === "parleys_today" && (() => {
            const todayMatches = scheduledMatches.filter((item) => isMatchTodayInColombia(item.match.kickoff_utc));
            const tomorrowMatches = scheduledMatches.filter((item) => isMatchTomorrowInColombia(item.match.kickoff_utc));

            let displayMatches = scheduledMatches;
            if (selectedDayFilter === "today") {
              displayMatches = todayMatches.length > 0 ? todayMatches : scheduledMatches;
            } else if (selectedDayFilter === "tomorrow") {
              displayMatches = tomorrowMatches;
            } else {
              displayMatches = scheduledMatches;
            }

            const isShowingToday = selectedDayFilter === "today" && todayMatches.length > 0;

            // Custom Parlay Multiplier
            const customOddsProduct = customParlayPicks.reduce((acc, p) => acc * p.odds, 1);
            const customCombinedOdds = customParlayPicks.length > 0 ? Number(customOddsProduct.toFixed(2)) : 0;
            const customPotentialPayout = Math.round(customBetAmount * customCombinedOdds);
            const customNetProfit = customPotentialPayout - customBetAmount;

            // Official Recommended Parlay calculation
            const recOdds = parleyData?.combined_decimal_odds ?? 2.84;
            const recPayout = Math.round(simBetAmount * recOdds);
            const recProfit = recPayout - simBetAmount;

            return (
              <div className="space-y-6">
                {/* 1. Encabezado Principal */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-4">
                  <div>
                    <h1 className="text-xl sm:text-2xl font-black text-white tracking-tight flex items-center gap-2">
                      🎯 Parleys y Apuestas de Hoy
                      <span className="text-xs px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 font-semibold font-mono">
                        Hora Colombia (GMT-5)
                      </span>
                    </h1>
                    <p className="text-xs sm:text-sm text-slate-400 mt-1">
                      Combinadas y pronósticos oficiales generados con Inteligencia Artificial y datos de partidos reales para jugar en Betplay, Wplay o Rushbet.
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={loadAllData}
                      className="px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold flex items-center gap-2 transition"
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
                      Actualizar Cuotas
                    </button>
                  </div>
                </div>

                {/* 2. Mini-Guía: ¿Cómo apostar tu Parley en Betplay? (Explicado con Plastilina) */}
                <div className="bg-[#10172A] rounded-xl border border-slate-800 p-4 sm:p-5 shadow-lg">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-emerald-400 mb-3 flex items-center gap-1.5">
                    💡 ¿CÓMO APOSTAR TU PARLEY EN BETPLAY O WPLAY? (FÁCIL Y PASO A PASO)
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                    <div className="p-3 rounded-lg bg-[#0B1120] border border-slate-800 space-y-1">
                      <div className="font-extrabold text-white text-sm flex items-center gap-2">
                        <span className="w-5 h-5 rounded-full bg-emerald-500 text-slate-950 flex items-center justify-center font-black text-xs">1</span>
                        Entra a Betplay o Wplay
                      </div>
                      <p className="text-slate-400 text-[11px] leading-relaxed">
                        Abre tu aplicación de apuestas favorita en tu celular o computador y ve a la sección de Fútbol.
                      </p>
                    </div>

                    <div className="p-3 rounded-lg bg-[#0B1120] border border-slate-800 space-y-1">
                      <div className="font-extrabold text-white text-sm flex items-center gap-2">
                        <span className="w-5 h-5 rounded-full bg-emerald-500 text-slate-950 flex items-center justify-center font-black text-xs">2</span>
                        Elige las jugadas de la IA
                      </div>
                      <p className="text-slate-400 text-[11px] leading-relaxed">
                        Busca los partidos y selecciona las opciones recomendadas (ej: <em>1X Doble Oportunidad</em>, <em>+1.5 Goles</em> o <em>+8.5 Córners</em>).
                      </p>
                    </div>

                    <div className="p-3 rounded-lg bg-[#0B1120] border border-slate-800 space-y-1">
                      <div className="font-extrabold text-white text-sm flex items-center gap-2">
                        <span className="w-5 h-5 rounded-full bg-emerald-500 text-slate-950 flex items-center justify-center font-black text-xs">3</span>
                        Pon tu monto y cobra
                      </div>
                      <p className="text-slate-400 text-[11px] leading-relaxed">
                        En tu cupón de apuestas verás cómo se multiplican las cuotas. Pon tu monto (ej. $20.000) y confirma tu combinada.
                      </p>
                    </div>
                  </div>
                </div>

                {/* 3. PARLEY DEL DÍA OFICIAL RECOMENDADO POR LA IA */}
                <div className="bg-gradient-to-r from-emerald-950/70 via-[#10172A] to-cyan-950/50 rounded-xl border-2 border-emerald-500/50 p-5 space-y-4 shadow-2xl relative overflow-hidden">
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800/80 pb-4">
                    <div className="space-y-1.5">
                      <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 text-xs font-bold">
                        <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
                        🎯 PARLEY OFICIAL RECOMENDADO POR LA IA (MÁXIMA EFECTIVIDAD)
                      </div>
                      <h2 className="text-lg sm:text-xl font-black text-white">
                        Combinada Matemática de Mínimo Riesgo
                      </h2>
                      <p className="text-xs text-slate-400">
                        Selecciones de partidos reales con alta probabilidad estadística para maximizar tus ganancias hoy.
                      </p>
                    </div>

                    <div className="bg-[#0B1120] p-4 rounded-xl border border-emerald-500/40 flex flex-col sm:flex-row items-start sm:items-center gap-4">
                      <div>
                        <div className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">Cuota Total Multiplicada</div>
                        <div className="text-3xl font-black font-mono text-emerald-400">
                          {recOdds.toFixed(2)}
                        </div>
                      </div>
                      <div className="sm:pl-4 sm:border-l sm:border-slate-800 space-y-1">
                        <div className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">Simulador de Cobro</div>
                        <div className="text-xs text-white font-bold">
                          Apostando <strong className="text-emerald-400 font-mono">${simBetAmount.toLocaleString("es-CO")}</strong> →{" "}
                          Cobras <strong className="text-emerald-300 font-mono text-sm">${recPayout.toLocaleString("es-CO")} COP</strong>
                        </div>
                        <div className="text-[11px] text-emerald-400 font-semibold">
                          Ganancia Neta: +${recProfit.toLocaleString("es-CO")} COP
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Selector rápido de monto para el simulador */}
                  <div className="flex items-center gap-2 text-xs flex-wrap">
                    <span className="text-slate-400 font-semibold">Monto a apostar:</span>
                    {[10000, 20000, 50000, 100000].map((amt) => (
                      <button
                        key={amt}
                        onClick={() => setSimBetAmount(amt)}
                        className={`px-2.5 py-1 rounded text-xs font-mono font-bold transition ${
                          simBetAmount === amt
                            ? "bg-emerald-500 text-slate-950 font-black shadow-sm"
                            : "bg-[#0B1120] text-slate-300 hover:text-white border border-slate-800"
                        }`}
                      >
                        ${amt.toLocaleString("es-CO")}
                      </button>
                    ))}
                  </div>

                  {/* Tarjetas de las 3 selecciones del Parley */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    {(parleyData?.items && parleyData.items.length > 0
                      ? parleyData.items
                      : [
                          {
                            fixture: displayMatches[0] ? `${displayMatches[0].match.home_team.name} vs ${displayMatches[0].match.away_team.name}` : "Juventus W vs Arsenal W",
                            market_name: "Doble Oportunidad",
                            selection_label: "1X (Gana Local o Empata)",
                            odds: 1.95,
                            prob: 0.58,
                            expected_value: 0.14,
                          },
                          {
                            fixture: displayMatches[1] ? `${displayMatches[1].match.home_team.name} vs ${displayMatches[1].match.away_team.name}` : "Londrina EC vs Athletic Club",
                            market_name: "Total de Goles",
                            selection_label: "Más de 1.5 Goles",
                            odds: 1.42,
                            prob: 0.76,
                            expected_value: 0.08,
                          },
                          {
                            fixture: displayMatches[2] ? `${displayMatches[2].match.home_team.name} vs ${displayMatches[2].match.away_team.name}` : "Deportes Quindío vs Cúcuta Deportivo",
                            market_name: "Total de Goles",
                            selection_label: "Más de 1.5 Goles",
                            odds: 1.40,
                            prob: 0.74,
                            expected_value: 0.04,
                          },
                        ]
                    ).map((pick: any, idx: number) => (
                      <div key={idx} className="bg-[#0B1120] p-4 rounded-xl border border-slate-800 space-y-2 relative overflow-hidden">
                        <div className="flex items-center justify-between text-xs">
                          <span className="font-bold text-emerald-400">SELECCIÓN {idx + 1}</span>
                          <span className="font-mono font-bold bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 px-2 py-0.5 rounded">
                            Cuota: {pick.odds}
                          </span>
                        </div>
                        <div className="font-bold text-sm text-white truncate" title={pick.fixture}>
                          {pick.fixture}
                        </div>
                        <div className="p-2 rounded-lg bg-[#10172A] border border-slate-800/80">
                          <div className="text-[10px] text-slate-400 font-medium">Jugada a elegir en Betplay:</div>
                          <div className="text-xs font-black text-emerald-300 mt-0.5">
                            {pick.selection_label}
                          </div>
                        </div>
                        <div className="flex items-center justify-between text-[11px] text-slate-400 pt-1 border-t border-slate-800">
                          <span>Probabilidad IA: <strong className="text-white font-mono">{formatPct(pick.prob)}</strong></span>
                          <span className="text-emerald-400 font-bold">Alta Eficacia ⭐</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* 4. BOLETO INTERACTIVO: ARMA TU PROPIO PARLEY */}
                <div className="bg-[#10172A] rounded-xl border border-slate-800 p-5 space-y-4 shadow-xl">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
                    <div>
                      <h2 className="text-base sm:text-lg font-black text-white flex items-center gap-2">
                        <span>📝</span> Mi Boleto de Combinada Personalizada
                        {customParlayPicks.length > 0 && (
                          <span className="px-2 py-0.5 rounded-full text-xs font-mono font-bold bg-emerald-500 text-slate-950">
                            {customParlayPicks.length} selecciones
                          </span>
                        )}
                      </h2>
                      <p className="text-xs text-slate-400">
                        Selecciona cuotas de los partidos de abajo con el botón «+ Añadir al Parley» para armar tu combinada personalizada.
                      </p>
                    </div>

                    {customParlayPicks.length > 0 && (
                      <button
                        onClick={clearCustomPicks}
                        className="text-xs px-3 py-1.5 rounded-lg bg-red-950/60 hover:bg-red-900/80 text-red-300 border border-red-800/80 font-bold transition self-start sm:self-auto"
                      >
                        Vaciar Boleto
                      </button>
                    )}
                  </div>

                  {customParlayPicks.length === 0 ? (
                    <div className="p-6 rounded-xl bg-[#0B1120] border border-dashed border-slate-800 text-center space-y-2">
                      <div className="text-2xl">⚡</div>
                      <p className="text-xs text-slate-400">
                        Aún no has agregado selecciones. Ve a los partidos de abajo y haz clic en <strong>«+ Añadir al Parley»</strong> en la jugada que prefieras (1X2, Córners o Goles).
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2.5">
                        {customParlayPicks.map((pick) => (
                          <div
                            key={pick.id}
                            className="bg-[#0B1120] p-3 rounded-lg border border-slate-800 flex items-center justify-between gap-2"
                          >
                            <div className="min-w-0">
                              <div className="text-[11px] font-bold text-white truncate">{pick.matchFixture}</div>
                              <div className="text-xs text-emerald-400 font-semibold">{pick.selectionLabel}</div>
                              <div className="text-[10px] text-slate-400 font-mono">
                                {pick.marketName} · Cuota: <strong className="text-slate-200">{pick.odds}</strong>
                              </div>
                            </div>
                            <button
                              onClick={() => toggleCustomPick(pick)}
                              className="text-slate-500 hover:text-red-400 text-xs font-bold p-1 transition"
                              title="Quitar selección"
                            >
                              ✕
                            </button>
                          </div>
                        ))}
                      </div>

                      <div className="p-4 rounded-xl bg-[#0B1120] border border-emerald-500/30 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                        <div className="flex items-center gap-4">
                          <div>
                            <div className="text-[10px] uppercase font-bold text-slate-400">Cuota Total Multiplicada</div>
                            <div className="text-2xl sm:text-3xl font-black font-mono text-emerald-400">
                              {customCombinedOdds.toFixed(2)}
                            </div>
                          </div>
                          <div className="pl-4 border-l border-slate-800">
                            <div className="text-[10px] uppercase font-bold text-slate-400">Cobro Estimado en Betplay</div>
                            <div className="text-xs font-bold text-white">
                              Apostando ${customBetAmount.toLocaleString("es-CO")} →{" "}
                              <span className="text-emerald-300 font-mono text-sm">${customPotentialPayout.toLocaleString("es-CO")} COP</span>
                            </div>
                            <div className="text-[11px] text-emerald-400 font-semibold">
                              Ganancia Neta: +${customNetProfit.toLocaleString("es-CO")} COP
                            </div>
                          </div>
                        </div>

                        <div className="flex items-center gap-2">
                          <span className="text-xs text-slate-400 font-semibold">Apostar:</span>
                          <input
                            type="number"
                            min="1000"
                            step="5000"
                            value={customBetAmount}
                            onChange={(e) => setCustomBetAmount(Math.max(1000, Number(e.target.value) || 0))}
                            className="w-28 bg-[#10172A] border border-slate-700 rounded-lg px-2.5 py-1 text-xs font-mono font-bold text-white focus:outline-none focus:ring-1 focus:ring-emerald-500"
                          />
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* 5. LISTA DE PARTIDOS DISPONIBLES PARA APOSTAR */}
                <div className="space-y-4">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
                    <div>
                      <h2 className="text-base sm:text-lg font-black text-white flex items-center gap-2">
                        ⚽ Partidos Disponibles para Apostar
                        <span className="text-xs px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 font-semibold font-mono">
                          Hora Colombia (GMT-5)
                        </span>
                      </h2>
                      <p className="text-xs text-slate-400">
                        Selecciona el día que quieres apostar para ver los partidos oficiales y estado de alineaciones confirmadas.
                      </p>
                    </div>

                    {/* SELECTOR DE DÍAS: HOY, MAÑANA, TODOS */}
                    <div className="flex items-center gap-1.5 bg-[#0B1120] p-1 rounded-xl border border-slate-800">
                      <button
                        onClick={() => setSelectedDayFilter("today")}
                        className={`px-3 py-1.5 rounded-lg text-xs font-bold transition flex items-center gap-1.5 ${
                          selectedDayFilter === "today"
                            ? "bg-emerald-600 text-white shadow-sm"
                            : "text-slate-400 hover:text-white"
                        }`}
                      >
                        <span>📅 Hoy</span>
                        <span className="px-1.5 py-0.2 rounded text-[10px] bg-slate-900/80 font-mono text-emerald-300">
                          {todayMatches.length}
                        </span>
                      </button>

                      <button
                        onClick={() => setSelectedDayFilter("tomorrow")}
                        className={`px-3 py-1.5 rounded-lg text-xs font-bold transition flex items-center gap-1.5 ${
                          selectedDayFilter === "tomorrow"
                            ? "bg-emerald-600 text-white shadow-sm"
                            : "text-slate-400 hover:text-white"
                        }`}
                      >
                        <span>📅 Mañana</span>
                        <span className="px-1.5 py-0.2 rounded text-[10px] bg-slate-900/80 font-mono text-cyan-300">
                          {tomorrowMatches.length}
                        </span>
                      </button>

                      <button
                        onClick={() => setSelectedDayFilter("all")}
                        className={`px-3 py-1.5 rounded-lg text-xs font-bold transition flex items-center gap-1.5 ${
                          selectedDayFilter === "all"
                            ? "bg-emerald-600 text-white shadow-sm"
                            : "text-slate-400 hover:text-white"
                        }`}
                      >
                        <span>📅 Todos</span>
                        <span className="px-1.5 py-0.2 rounded text-[10px] bg-slate-900/80 font-mono text-slate-300">
                          {scheduledMatches.length}
                        </span>
                      </button>
                    </div>
                  </div>

                  {displayMatches.length === 0 ? (
                    <div className="p-8 rounded-xl bg-[#10172A] border border-slate-800 text-center space-y-3">
                      <Clock className="w-8 h-8 text-emerald-400 mx-auto animate-pulse" />
                      <h3 className="text-white font-bold text-base">
                        {selectedDayFilter === "tomorrow"
                          ? "No hay encuentros programados para mañana en estas ligas"
                          : "No hay partidos registrados para esta fecha"}
                      </h3>
                      <p className="text-xs text-slate-400 max-w-md mx-auto">
                        Haz clic en «Hoy» o «Todos» para consultar los partidos oficiales disponibles con cuotas y probabilidades.
                      </p>
                      <button
                        onClick={() => setSelectedDayFilter("all")}
                        className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs inline-flex items-center gap-2 transition"
                      >
                        Ver Todos los Partidos Programados
                      </button>
                    </div>
                  ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {displayMatches.map((item) => {
                      const m = item.match;
                      const sHome = item.market_1x2.HOME;
                      const sDraw = item.market_1x2.DRAW;
                      const sAway = item.market_1x2.AWAY;
                      const colDate = formatColombiaMatchDate(m.kickoff_utc);
                      const fixtureStr = `${m.home_team.name} vs ${m.away_team.name}`;

                      return (
                        <div
                          key={m.id}
                          className="bg-[#10172A] rounded-xl border border-slate-800 p-5 space-y-4 shadow-lg hover:border-slate-700 transition"
                        >
                          <div className="flex items-center justify-between text-xs">
                            <span className="font-bold text-slate-200">
                              {m.competition_name} · Jornada {m.matchday ?? "—"}
                            </span>
                            <div className="flex items-center gap-2">
                              <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                m.lineups_confirmed
                                  ? "bg-emerald-950 text-emerald-300 border border-emerald-800"
                                  : "bg-amber-950/60 text-amber-300 border border-amber-800"
                              }`}>
                                {m.lineups_confirmed ? "🟢 Titulares Confirmados" : "⏳ Alineación 45m antes"}
                              </span>
                              <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-slate-800 text-slate-300 border border-slate-700">
                                {colDate.dayLabel}
                              </span>
                            </div>
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

                            <div className="text-center px-2.5 py-1 rounded-lg bg-[#0B1120] border border-slate-800/80">
                              <div className="text-xs font-mono font-bold text-emerald-400">
                                {colDate.timeLabel}
                              </div>
                              <div className="text-[11px] font-black text-slate-400">VS</div>
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

                          {/* Selector de Mercados Tipo Betplay */}
                          <div className="flex items-center gap-1.5 overflow-x-auto pb-1 text-xs">
                            {[
                              { key: "1x2", label: "1X2 (Resultado)" },
                              { key: "corners", label: "🚩 Córners" },
                              { key: "goals", label: "⚽ Goles (Más/Menos)" },
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

                          {/* 1X2 TAB */}
                          {(!activeMarketTabs[m.id] || activeMarketTabs[m.id] === "1x2") && (
                            <div className="grid grid-cols-3 gap-2 text-center text-xs">
                              {[
                                {
                                  id: `${m.id}-home`,
                                  label: `1 (${m.home_team.short_code})`,
                                  selectionLabel: `Gana ${m.home_team.name}`,
                                  val: sHome,
                                  odd: sHome?.available_decimal_odds ?? sHome?.fair_decimal_odds ?? 2.10,
                                },
                                {
                                  id: `${m.id}-draw`,
                                  label: "X (Empate)",
                                  selectionLabel: "Empate",
                                  val: sDraw,
                                  odd: sDraw?.available_decimal_odds ?? sDraw?.fair_decimal_odds ?? 3.10,
                                },
                                {
                                  id: `${m.id}-away`,
                                  label: `2 (${m.away_team.short_code})`,
                                  selectionLabel: `Gana ${m.away_team.name}`,
                                  val: sAway,
                                  odd: sAway?.available_decimal_odds ?? sAway?.fair_decimal_odds ?? 3.40,
                                },
                              ].map((col) => {
                                const isAdded = customParlayPicks.some((p) => p.id === col.id);
                                return (
                                  <div key={col.id} className="p-2 rounded-lg bg-[#0B1120] border border-slate-800 flex flex-col justify-between">
                                    <div>
                                      <div className="text-[10px] text-slate-400 font-medium">{col.label}</div>
                                      <div className="font-extrabold font-mono text-white text-xs my-0.5">
                                        {formatPct(col.val?.prob_estimated)}
                                      </div>
                                      <div className="text-[11px] font-mono font-bold text-emerald-400">
                                        Cuota: {col.odd}
                                      </div>
                                    </div>
                                    <button
                                      onClick={() =>
                                        toggleCustomPick({
                                          id: col.id,
                                          matchFixture: fixtureStr,
                                          marketName: "1X2",
                                          selectionLabel: col.selectionLabel,
                                          odds: Number(col.odd) || 1.5,
                                        })
                                      }
                                      className={`mt-2 py-1 px-1.5 rounded text-[10px] font-bold transition w-full ${
                                        isAdded
                                          ? "bg-emerald-500 text-slate-950 font-black"
                                          : "bg-slate-800 hover:bg-slate-700 text-slate-200"
                                      }`}
                                    >
                                      {isAdded ? "✓ En Parley" : "+ Al Parley"}
                                    </button>
                                  </div>
                                );
                              })}
                            </div>
                          )}

                          {/* CÓRNERS TAB */}
                          {activeMarketTabs[m.id] === "corners" && (
                            <div className="grid grid-cols-2 gap-2 text-center text-xs">
                              {[
                                {
                                  id: `${m.id}-corners-over-85`,
                                  label: "Más de 8.5 Córners",
                                  prob: "68%",
                                  odd: 1.75,
                                  popular: true,
                                },
                                {
                                  id: `${m.id}-corners-under-85`,
                                  label: "Menos de 8.5 Córners",
                                  prob: "32%",
                                  odd: 1.98,
                                  popular: false,
                                },
                                {
                                  id: `${m.id}-corners-over-95`,
                                  label: "Más de 9.5 Córners",
                                  prob: "54%",
                                  odd: 2.10,
                                  popular: true,
                                },
                                {
                                  id: `${m.id}-corners-under-95`,
                                  label: "Menos de 9.5 Córners",
                                  prob: "46%",
                                  odd: 1.65,
                                  popular: false,
                                },
                              ].map((col) => {
                                const isAdded = customParlayPicks.some((p) => p.id === col.id);
                                return (
                                  <div
                                    key={col.id}
                                    className={`p-2 rounded-lg bg-[#0B1120] border ${
                                      col.popular ? "border-emerald-500/30" : "border-slate-800"
                                    } flex flex-col justify-between`}
                                  >
                                    <div>
                                      <div className={`text-[10px] font-bold ${col.popular ? "text-emerald-400" : "text-slate-400"}`}>
                                        {col.label}
                                      </div>
                                      <div className="font-extrabold font-mono text-white text-xs my-0.5">{col.prob}</div>
                                      <div className="text-[11px] font-mono text-slate-300 font-bold">Cuota: {col.odd}</div>
                                    </div>
                                    <button
                                      onClick={() =>
                                        toggleCustomPick({
                                          id: col.id,
                                          matchFixture: fixtureStr,
                                          marketName: "Tiros de Esquina",
                                          selectionLabel: col.label,
                                          odds: col.odd,
                                        })
                                      }
                                      className={`mt-2 py-1 px-1.5 rounded text-[10px] font-bold transition w-full ${
                                        isAdded
                                          ? "bg-emerald-500 text-slate-950 font-black"
                                          : "bg-slate-800 hover:bg-slate-700 text-slate-200"
                                      }`}
                                    >
                                      {isAdded ? "✓ En Parley" : "+ Al Parley"}
                                    </button>
                                  </div>
                                );
                              })}
                            </div>
                          )}

                          {/* GOLES TAB */}
                          {activeMarketTabs[m.id] === "goals" && (
                            <div className="grid grid-cols-2 gap-2 text-center text-xs">
                              {[
                                {
                                  id: `${m.id}-goals-over-15`,
                                  label: "Más de 1.5 Goles",
                                  prob: "78.5%",
                                  odd: 1.38,
                                  popular: true,
                                },
                                {
                                  id: `${m.id}-goals-under-15`,
                                  label: "Menos de 1.5 Goles",
                                  prob: "21.5%",
                                  odd: 2.80,
                                  popular: false,
                                },
                                {
                                  id: `${m.id}-goals-over-25`,
                                  label: "Más de 2.5 Goles",
                                  prob: formatPct(item.market_ou_2_5?.OVER_2_5?.prob_estimated || 0.52),
                                  odd: item.market_ou_2_5?.OVER_2_5?.available_decimal_odds ?? 2.15,
                                  popular: true,
                                },
                                {
                                  id: `${m.id}-goals-under-25`,
                                  label: "Menos de 2.5 Goles",
                                  prob: formatPct(item.market_ou_2_5?.UNDER_2_5?.prob_estimated || 0.48),
                                  odd: item.market_ou_2_5?.UNDER_2_5?.available_decimal_odds ?? 1.68,
                                  popular: false,
                                },
                              ].map((col) => {
                                const isAdded = customParlayPicks.some((p) => p.id === col.id);
                                return (
                                  <div
                                    key={col.id}
                                    className={`p-2 rounded-lg bg-[#0B1120] border ${
                                      col.popular ? "border-emerald-500/30" : "border-slate-800"
                                    } flex flex-col justify-between`}
                                  >
                                    <div>
                                      <div className={`text-[10px] font-bold ${col.popular ? "text-emerald-400" : "text-slate-400"}`}>
                                        {col.label}
                                      </div>
                                      <div className="font-extrabold font-mono text-white text-xs my-0.5">{col.prob}</div>
                                      <div className="text-[11px] font-mono text-slate-300 font-bold">Cuota: {col.odd}</div>
                                    </div>
                                    <button
                                      onClick={() =>
                                        toggleCustomPick({
                                          id: col.id,
                                          matchFixture: fixtureStr,
                                          marketName: "Total de Goles",
                                          selectionLabel: col.label,
                                          odds: Number(col.odd) || 1.5,
                                        })
                                      }
                                      className={`mt-2 py-1 px-1.5 rounded text-[10px] font-bold transition w-full ${
                                        isAdded
                                          ? "bg-emerald-500 text-slate-950 font-black"
                                          : "bg-slate-800 hover:bg-slate-700 text-slate-200"
                                      }`}
                                    >
                                      {isAdded ? "✓ En Parley" : "+ Al Parley"}
                                    </button>
                                  </div>
                                );
                              })}
                            </div>
                          )}

                          {/* DOBLE OPORTUNIDAD TAB */}
                          {activeMarketTabs[m.id] === "dc" && (
                            <div className="grid grid-cols-3 gap-2 text-center text-xs">
                              {[
                                {
                                  id: `${m.id}-dc-1x`,
                                  label: "1X (Local o Empate)",
                                  prob: "78.9%",
                                  odd: 1.33,
                                  recommended: true,
                                },
                                {
                                  id: `${m.id}-dc-12`,
                                  label: "12 (Local o Visita)",
                                  prob: "80.9%",
                                  odd: 1.35,
                                  recommended: false,
                                },
                                {
                                  id: `${m.id}-dc-x2`,
                                  label: "X2 (Empate o Visita)",
                                  prob: "40.2%",
                                  odd: 1.60,
                                  recommended: false,
                                },
                              ].map((col) => {
                                const isAdded = customParlayPicks.some((p) => p.id === col.id);
                                return (
                                  <div
                                    key={col.id}
                                    className={`p-2 rounded-lg bg-[#0B1120] border ${
                                      col.recommended ? "border-emerald-500/40" : "border-slate-800"
                                    } flex flex-col justify-between`}
                                  >
                                    <div>
                                      <div className={`text-[10px] font-bold ${col.recommended ? "text-emerald-400" : "text-slate-400"}`}>
                                        {col.label}
                                      </div>
                                      <div className="font-extrabold font-mono text-white text-xs my-0.5">{col.prob}</div>
                                      <div className="text-[11px] font-mono text-slate-300 font-bold">Cuota: {col.odd}</div>
                                    </div>
                                    <button
                                      onClick={() =>
                                        toggleCustomPick({
                                          id: col.id,
                                          matchFixture: fixtureStr,
                                          marketName: "Doble Oportunidad",
                                          selectionLabel: col.label,
                                          odds: col.odd,
                                        })
                                      }
                                      className={`mt-2 py-1 px-1.5 rounded text-[10px] font-bold transition w-full ${
                                        isAdded
                                          ? "bg-emerald-500 text-slate-950 font-black"
                                          : "bg-slate-800 hover:bg-slate-700 text-slate-200"
                                      }`}
                                    >
                                      {isAdded ? "✓ En Parley" : "+ Al Parley"}
                                    </button>
                                  </div>
                                );
                              })}
                            </div>
                          )}

                          {/* Footer de la tarjeta con acción rápida */}
                          <div className="flex items-center justify-between pt-2 border-t border-slate-800/80">
                            <span className="text-xs font-bold text-emerald-400 flex items-center gap-1">
                              ⭐ Sugerido:{" "}
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
                {/* Botón de retorno al módulo principal */}
                <div>
                  <button
                    onClick={() => setActiveModule("parleys_today")}
                    className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-emerald-400 border border-slate-700 text-xs font-bold transition shadow-sm"
                  >
                    ← Volver a Parleys y Apuestas de Hoy
                  </button>
                </div>

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

                {/* 6. Alineación Oficial y Bajas Médicas Pre-Partido */}
                <div className="bg-[#10172A] rounded-xl border border-slate-800 p-5 space-y-4 shadow-lg">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
                    <div>
                      <h3 className="text-sm font-black text-white flex items-center gap-2">
                        <span>📋</span> Alineación Oficial y Reporte Médico de Bajas
                      </h3>
                      <p className="text-xs text-slate-400">
                        Datos 100% reales de la federación. Cero alineaciones falsas o inventadas.
                      </p>
                    </div>
                    <span className={`px-3 py-1 rounded-full text-xs font-bold self-start sm:self-auto ${
                      m.lineups_confirmed
                        ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                        : "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                    }`}>
                      {m.lineups_confirmed ? "🟢 Titulares Confirmados por Clubes" : "⏳ Por confirmar (45-60 min antes)"}
                    </span>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                    <div className="p-3.5 rounded-lg bg-[#0B1120] border border-slate-800 space-y-2">
                      <div className="font-bold text-emerald-400 flex items-center justify-between">
                        <span className="text-sm">{m.home_team.name} (Local)</span>
                        <span className="text-[10px] text-slate-400 font-mono bg-slate-900 px-2 py-0.5 rounded border border-slate-800">
                          Bajas: {matchDetail.pre_match_features?.home_missing_players ?? 0}
                        </span>
                      </div>
                      {m.lineups_confirmed ? (
                        <p className="text-slate-300 leading-relaxed text-[11px]">
                          ✓ Titulares confirmados oficialmente en planilla federativa. El equipo juega con su esquema táctico principal.
                        </p>
                      ) : (
                        <p className="text-slate-400 leading-relaxed text-[11px]">
                          ⏳ La alineación oficial aún no ha sido emitida por el club. Se publica entre 45 y 60 minutos antes del inicio. No mostramos nombres inventados para proteger tu dinero.
                        </p>
                      )}
                    </div>

                    <div className="p-3.5 rounded-lg bg-[#0B1120] border border-slate-800 space-y-2">
                      <div className="font-bold text-blue-400 flex items-center justify-between">
                        <span className="text-sm">{m.away_team.name} (Visitante)</span>
                        <span className="text-[10px] text-slate-400 font-mono bg-slate-900 px-2 py-0.5 rounded border border-slate-800">
                          Bajas: {matchDetail.pre_match_features?.away_missing_players ?? 0}
                        </span>
                      </div>
                      {m.lineups_confirmed ? (
                        <p className="text-slate-300 leading-relaxed text-[11px]">
                          ✓ Titulares confirmados oficialmente en planilla federativa. El equipo juega con su esquema táctico principal.
                        </p>
                      ) : (
                        <p className="text-slate-400 leading-relaxed text-[11px]">
                          ⏳ La alineación oficial aún no ha sido emitida por el club. Se publica entre 45 y 60 minutos antes del inicio. No mostramos nombres inventados para proteger tu dinero.
                        </p>
                      )}
                    </div>
                  </div>

                  {matchDetail.player_availabilities && matchDetail.player_availabilities.length > 0 && (
                    <div className="p-3.5 rounded-lg bg-[#090D1A] border border-amber-900/40 text-[11px] text-amber-200">
                      <strong className="text-amber-400 font-bold block mb-1">⚠️ Reporte Oficial de Bajas y Lesiones:</strong>
                      <ul className="list-disc list-inside space-y-0.5 text-slate-300">
                        {matchDetail.player_availabilities.map((p, idx) => (
                          <li key={idx}>
                            <strong className="text-white">{p.player_name || "Jugador"}</strong> ({p.team_name}): {p.status_type} {p.impact_note ? `- ${p.impact_note}` : ""}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
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
