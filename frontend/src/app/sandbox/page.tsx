"use client";

import { CopilotKit, useCopilotChatInternal } from "@copilotkit/react-core";
import { motion, AnimatePresence, LayoutGroup } from "motion/react";
import { Zap, Target, Activity, Database, Send, Sparkles, Clock, ChevronRight } from "lucide-react";

// Deterministic short hash from any string.
// Two strings that are equal will ALWAYS produce the same hash,
// allowing Framer Motion to detect shared elements across turns.
function contentHash(str: string): string {
  let h = 0;
  for (let i = 0; i < str.length; i++) {
    h = (Math.imul(31, h) + str.charCodeAt(i)) | 0;
  }
  return Math.abs(h).toString(36);
}
import { useState, useRef, useEffect, useMemo } from "react";

export default function SandboxPage() {
  return (
    <CopilotKit runtimeUrl="/api/copilotkit">
      <SandboxContent />
    </CopilotKit>
  );
}

// -- DATA MODELS --
type InteractionTurn = {
  id: string;
  userMessage: any;
  assistantMessages: any[];
};

function deriveTurnsFromMessages(messages: any[]): InteractionTurn[] {
  const turns: InteractionTurn[] = [];
  let currentTurn: InteractionTurn | null = null;

  for (const msg of messages) {
    // Ignore pure system messages that aren't tied to a user prompt, unless we want to show them.
    if (msg.role === "user") {
      if (currentTurn) {
        turns.push(currentTurn);
      }
      currentTurn = {
        id: msg.id,
        userMessage: msg,
        assistantMessages: [],
      };
    } else if (currentTurn && msg.role !== "system") {
      currentTurn.assistantMessages.push(msg);
    }
  }
  
  if (currentTurn) {
    turns.push(currentTurn);
  }
  
  return turns;
}

// -- MAIN COMPONENT --
function SandboxContent() {
  const { messages, sendMessage, isLoading, setMessages } = useCopilotChatInternal();
  const [inputValue, setInputValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Time Travel State
  const turns = useMemo(() => deriveTurnsFromMessages(messages || []), [messages]);
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);

  // If the user hasn't explicitly traveled back in time, always follow the latest turn
  const latestTurnId = turns.length > 0 ? turns[turns.length - 1].id : null;
  const isNavigatingHistory = activeTurnId !== null && activeTurnId !== latestTurnId;
  const currentDisplayedTurnId = isNavigatingHistory ? activeTurnId : latestTurnId;
  
  const activeTurn = turns.find(t => t.id === currentDisplayedTurnId);
  const isIdle = turns.length === 0;

  // Sync active turn to latest when new messages arrive (if not time traveling)
  useEffect(() => {
    if (!isNavigatingHistory && latestTurnId) {
      setActiveTurnId(latestTurnId);
    }
  }, [latestTurnId, isNavigatingHistory]);

  const handleSubmit = async (e?: React.FormEvent, directText?: string) => {
    e?.preventDefault();
    const text = directText || inputValue;
    if (!text.trim() || isLoading) return;
    
    // Context Pruning: If we are time traveling and we send a new message,
    // we must prune the alternate future from CopilotKit's memory.
    if (isNavigatingHistory && activeTurnId) {
      const activeTurnIndex = turns.findIndex(t => t.id === activeTurnId);
      if (activeTurnIndex !== -1) {
        // Find the index in raw messages of the active turn's user message
        const targetMessage = turns[activeTurnIndex].userMessage;
        const rawIndex = messages.findIndex(m => m.id === targetMessage.id);
        
        // We want to keep everything up to this turn's assistant messages
        // Actually, the easiest way is to find the index of the next turn's user message
        const nextTurn = turns[activeTurnIndex + 1];
        if (nextTurn) {
          const cutIndex = messages.findIndex(m => m.id === nextTurn.userMessage.id);
          if (cutIndex !== -1) {
             const prunedMessages = messages.slice(0, cutIndex);
             // CopilotKit messages carry internal function references (e.g. legacyCustomMessageRenderer)
             // that structuredClone cannot serialize. Strip them down to plain data objects.
             const serializable = prunedMessages.map((m: any) => ({
               id: m.id,
               role: m.role,
               content: m.content ?? "",
               ...(m.type && { type: m.type }),
               ...(m.name && { name: m.name }),
               ...(m.toolCalls && { toolCalls: m.toolCalls }),
             }));
             setMessages(serializable as any);
          }
        }
      }
    }
    
    setInputValue("");
    // Snap to present
    setActiveTurnId(null);
    
    try {
      await sendMessage({
        id: Date.now().toString(),
        role: "user",
        content: text,
      });
    } catch (err) {
      console.error("Failed to send message", err);
    }
  };

  return (
    <div className="min-h-screen bg-[#0A0A0B] text-white flex flex-col font-sans relative overflow-hidden" ref={containerRef}>
      {/* Dynamic Ambient Backgrounds */}
      <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] bg-indigo-500/10 blur-[120px] rounded-full pointer-events-none" />
      <div className="absolute bottom-[-20%] right-[-10%] w-[50%] h-[50%] bg-purple-500/10 blur-[120px] rounded-full pointer-events-none" />

      <LayoutGroup>
        
        {/* -- HISTORY SIDEBAR / TOP NAV -- */}
        <AnimatePresence>
          {turns.length > 1 && (
            <motion.div 
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              className="absolute top-0 left-0 w-full flex items-center gap-4 z-50 pointer-events-auto px-6 py-4 overflow-x-auto overflow-y-hidden border-b border-white/5 bg-[#0A0A0B]/80 backdrop-blur-xl [&::-webkit-scrollbar]:hidden"
            >
              <div className="flex items-center gap-2 text-xs font-semibold text-gray-500 uppercase tracking-widest shrink-0 mr-2">
                <Clock className="w-4 h-4" /> Memoria
              </div>
              {turns.map((turn, i) => {
                const isActive = turn.id === currentDisplayedTurnId;
                return (
                  <motion.button
                    key={turn.id}
                    layoutId={`history-node-${turn.id}`}
                    onClick={() => setActiveTurnId(turn.id)}
                    className={`group relative flex items-center p-3 rounded-2xl border transition-all duration-300 text-left shrink-0 max-w-[200px] backdrop-blur-md ${
                      isActive 
                        ? "bg-indigo-500/20 border-indigo-500/50 shadow-[0_0_20px_rgba(99,102,241,0.2)]" 
                        : "bg-white/5 border-white/5 hover:bg-white/10"
                    }`}
                  >
                    <div className="flex-1 truncate pr-4 text-sm font-medium text-gray-200">
                      {turn.userMessage.content}
                    </div>
                    {isActive && (
                      <motion.div layoutId="active-indicator" className="absolute right-3 w-2 h-2 rounded-full bg-indigo-400 shadow-[0_0_10px_rgba(99,102,241,0.8)]" />
                    )}
                  </motion.button>
                );
              })}
              
              {isNavigatingHistory && (
                <motion.button
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  onClick={() => setActiveTurnId(latestTurnId)}
                  className="flex items-center gap-2 justify-center px-4 py-2.5 rounded-xl bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/30 transition-all text-sm font-semibold shrink-0 ml-auto"
                >
                  Volver al Presente
                </motion.button>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {/* -- MAIN CANVAS -- */}
        <AnimatePresence mode="wait">
          {isIdle ? (
            <motion.div 
              key="idle"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 1.05, filter: "blur(10px)" }}
              transition={{ type: "spring", stiffness: 260, damping: 20 }}
              className="flex-1 flex flex-col items-center justify-center p-6 z-10"
            >
              <motion.div layoutId="ai-avatar" className="w-20 h-20 rounded-3xl bg-gradient-to-tr from-indigo-500 to-purple-500 flex items-center justify-center mb-8 shadow-[0_0_60px_rgba(99,102,241,0.4)]">
                <Sparkles className="w-10 h-10 text-white" />
              </motion.div>
              
              <motion.h1 layoutId="main-title" className="text-5xl md:text-6xl font-bold tracking-tight mb-4 text-center text-transparent bg-clip-text bg-gradient-to-b from-white to-white/60">
                ¿En qué te ayudo hoy?
              </motion.h1>
              
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 w-full max-w-3xl mt-12">
                <PromptCard icon={<Database className="w-5 h-5 text-blue-400" />} title="Estado del Inventario" description="Revisar stock de la bodega norte" onClick={() => handleSubmit(undefined, "Revisar stock de la bodega norte")} />
                <PromptCard icon={<Target className="w-5 h-5 text-rose-400" />} title="Predicción de Ventas" description="Proyectar Q3 basado en históricos" onClick={() => handleSubmit(undefined, "Proyectar Q3 basado en históricos")} />
                <PromptCard icon={<Activity className="w-5 h-5 text-emerald-400" />} title="Análisis de Rendimiento" description="Comparar KPIs de este mes vs anterior" onClick={() => handleSubmit(undefined, "Comparar KPIs de este mes vs anterior")} />
                <PromptCard icon={<Zap className="w-5 h-5 text-amber-400" />} title="Automatización" description="Configurar alertas de bajo stock" onClick={() => handleSubmit(undefined, "Configurar alertas de bajo stock")} />
              </div>
            </motion.div>
          ) : (
            <motion.div 
              key={`canvas-${contentHash(activeTurn?.assistantMessages.map((m: any) => m.content).join('|') ?? '')}`}
              initial={{ opacity: 0, y: 30, filter: "blur(10px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              exit={{ opacity: 0, y: -30, filter: "blur(10px)" }}
              transition={{ type: "spring", stiffness: 300, damping: 25 }}
              className="flex-1 w-full max-w-5xl mx-auto flex flex-col items-center pt-[15vh] px-8 pb-40 z-10"
            >
              {/* Context Header (User Prompt) — layoutId based on prompt text so identical prompts persist */}
              <motion.div layoutId={`prompt-context-${contentHash(activeTurn?.userMessage.content ?? '')}`} className="flex items-center gap-4 mb-12">
                <div className="h-px w-12 bg-indigo-500/30" />
                <h2 className="text-2xl font-medium text-indigo-200 tracking-tight">
                  {activeTurn?.userMessage.content}
                </h2>
                <div className="h-px w-12 bg-indigo-500/30" />
              </motion.div>

              {/* Assistant Response Canvas */}
              <div className="w-full flex flex-col items-center space-y-8">
                {activeTurn?.assistantMessages.map((msg, i) => {
                  // Use content hash so two messages with the same text share the same
                  // layoutId — Framer Motion will morph instead of destroy/create.
                  const cHash = contentHash(msg.content ?? '');
                  return (
                  <motion.div 
                    key={`response-${cHash}`}
                    layoutId={`response-${cHash}`}
                    drag
                    dragConstraints={containerRef}
                    whileDrag={{ scale: 1.02, zIndex: 50, cursor: "grabbing" }}
                    className="w-full max-w-4xl p-8 rounded-[2rem] bg-white/5 border border-white/10 backdrop-blur-2xl shadow-2xl cursor-grab hover:border-white/20 transition-colors"
                  >
                    <div className="flex items-start gap-6">
                      <motion.div layoutId="ai-avatar-small" className="w-12 h-12 rounded-2xl bg-indigo-500/20 flex items-center justify-center shrink-0 border border-indigo-500/30">
                        <Sparkles className="w-6 h-6 text-indigo-400" />
                      </motion.div>
                      <div className="flex-1 pt-1">
                        <div className="prose prose-invert prose-lg md:prose-xl max-w-none text-gray-200 leading-relaxed font-light">
                          {msg.content || "..."}
                        </div>
                      </div>
                    </div>
                  </motion.div>
                  );
                })}

                {isLoading && currentDisplayedTurnId === latestTurnId && (
                   <motion.div 
                      initial={{ opacity: 0, scale: 0.9 }}
                      animate={{ opacity: 1, scale: 1 }}
                      className="p-6 rounded-3xl bg-indigo-500/10 border border-indigo-500/20 flex items-center gap-4 text-indigo-300"
                   >
                     <Sparkles className="w-5 h-5 animate-pulse" />
                     <span className="font-medium tracking-wide">Analizando el contexto...</span>
                   </motion.div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* -- FIXED INPUT WORKSPACE -- */}
        <motion.div 
          layoutId="input-workspace"
          className="absolute bottom-8 w-full px-4 z-50 pointer-events-none flex justify-center"
        >
          <div className="w-full max-w-3xl pointer-events-auto">
            <form 
              onSubmit={(e) => handleSubmit(e)}
              className="relative flex items-center group"
            >
              {/* Magic Glow */}
              <div className="absolute inset-0 bg-gradient-to-r from-indigo-500/20 to-purple-500/20 blur-2xl opacity-0 group-hover:opacity-100 transition-opacity rounded-[2rem]" />
              
              <div className="relative w-full flex items-center bg-[#151517]/90 backdrop-blur-3xl border border-white/10 rounded-[2rem] shadow-[0_20px_60px_rgba(0,0,0,0.4)] overflow-hidden p-2">
                <div className="pl-6 pr-2 text-indigo-400/50">
                  <ChevronRight className="w-6 h-6" />
                </div>
                <input
                  ref={inputRef}
                  type="text"
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  placeholder={isNavigatingHistory ? "Escribir creará una nueva línea temporal..." : "Colaborar con ARIA..."}
                  className="w-full bg-transparent border-none text-white text-lg px-2 py-5 focus:outline-none focus:ring-0 placeholder:text-gray-500 placeholder:font-light font-medium"
                  disabled={isLoading}
                />
                <button
                  type="submit"
                  disabled={!inputValue.trim() || isLoading}
                  className="p-4 rounded-2xl bg-indigo-500/20 text-indigo-400 hover:bg-indigo-500 hover:text-white transition-all duration-300 disabled:opacity-50 disabled:bg-transparent disabled:text-gray-600 mr-2 hover:scale-105 active:scale-95"
                >
                  <Send className="w-5 h-5" />
                </button>
              </div>
            </form>
          </div>
        </motion.div>

      </LayoutGroup>
    </div>
  );
}

// -- WIDGETS & CARDS --
function PromptCard({ icon, title, description, onClick }: { icon: React.ReactNode, title: string, description: string, onClick: () => void }) {
  return (
    <motion.button 
      layout
      whileHover={{ y: -4, scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
      onClick={onClick}
      className="group flex flex-col text-left p-6 rounded-[2rem] bg-white/5 border border-white/5 hover:bg-white/10 hover:border-white/10 transition-colors shadow-lg"
    >
      <div className="w-12 h-12 rounded-2xl bg-black/40 flex items-center justify-center mb-5 group-hover:scale-110 transition-transform duration-300">
        {icon}
      </div>
      <h3 className="text-white font-semibold mb-2 text-xl tracking-tight">{title}</h3>
      <p className="text-gray-400 text-sm leading-relaxed font-light">{description}</p>
    </motion.button>
  );
}
