-- EXODIA-4B :: Left Arm (peca 1/5)
-- Ponte BizHawk -> Python. Roda DENTRO do EmuHawk.
--
-- Como usar:
--   1. Suba o servidor Python (exodia/bridge.py) PRIMEIRO.
--   2. EmuHawk.exe --socket_ip=127.0.0.1 --socket_port=55355 --lua=<este arquivo> <rom>
--
-- Protocolo: o Python e o SERVIDOR, o BizHawk e o CLIENTE.
-- A cada iteracao o Lua manda o resultado do comando anterior e recebe o proximo.
-- O Python DEVE prefixar suas respostas com "<tamanho> " (exigencia do BizHawk >= 2.6.2).

-- Quanto o Lua espera por um comando antes de desistir e adiantar um frame.
--
-- Era 50 ms, e isso fazia o jogo ANDAR SOZINHO enquanto o modelo pensava: uma
-- inferencia de 30 s virava ~600 frames de jogo rodando sem ninguem no
-- controle. O agente decidia sobre um estado e agia sobre outro.
--
-- Com 2 s o emulador fica praticamente congelado durante a inferencia - que e
-- justamente a premissa do projeto: o jogo e por turnos e espera por nos, entao
-- latencia custa tempo de relogio, nunca qualidade de jogo. E de quebra o
-- BizHawk para de disputar CPU com o Ollama.
--
-- Nao e infinito de proposito: se o processo Python morrer, o EmuHawk volta a
-- responder em 2 s e da para fechar a janela na mao.
local POLL_TIMEOUT_MS = 2000

comm.socketServerSetTimeout(POLL_TIMEOUT_MS)

-- ---------------------------------------------------------------- utilidades

local function hexdump(bytes)
  local t = {}
  for i = 1, #bytes do t[i] = string.format("%02X", bytes[i]) end
  return table.concat(t)
end

local function split(s)
  local t = {}
  for w in string.gmatch(s, "%S+") do t[#t + 1] = w end
  return t
end

-- Le n bytes crus a partir de addr no dominio informado (default MainRAM).
-- IMPORTANTE: mascara 0x1FFFFF converte endereco PS1 (0x800xxxxx) em offset MainRAM.
local function read_range(addr, len, domain)
  domain = domain or "MainRAM"
  local out = {}
  for i = 0, len - 1 do
    out[i + 1] = memory.read_u8(addr + i, domain)
  end
  return out
end

-- ---------------------------------------------------------------- comandos

local BUTTONS = {}  -- cache do nome do controle

local function press(button, frames)
  frames = frames or 2
  for _ = 1, frames do
    local t = {}
    t[button] = true
    joypad.set(t, 1)
    emu.frameadvance()
  end
  -- solta e deixa 1 frame limpo
  emu.frameadvance()
  return "OK"
end

local handlers = {}

handlers.PING = function() return "PONG" end

-- BUTTONS -> nomes EXATOS dos botoes aceitos por joypad.set neste core,
-- cada um acompanhado dos seus bytes em hex.
-- Nunca adivinhe: no core PSX o D-pad e "D-Pad Right" (nao "Right") e o
-- botao de confirmar e "X" (nao "Cross"). Circulo/quadrado/triangulo sao
-- simbolos Unicode, por isso o hex - evita qualquer duvida de encoding.
local function tohex(s)
  return (s:gsub(".", function(c) return string.format("%02X", c:byte()) end))
end

handlers.BUTTONS = function()
  local t = {}
  for name, _ in pairs(joypad.get(1)) do
    t[#t + 1] = tohex(name) .. ":" .. name
  end
  table.sort(t)
  return table.concat(t, ",")
end

local function fromhex(h)
  return (h:gsub("%x%x", function(cc)
    return string.char(tonumber(cc, 16))
  end))
end

-- PRESSHEX <hex_do_nome> [frames] -> aperta o botao endereçado por bytes
handlers.PRESSHEX = function(a)
  local name = fromhex(a[2] or "")
  if name == "" then return "ERR hex vazio" end
  return press(name, tonumber(a[3]))
end

handlers.INFO = function()
  local parts = {
    "system=" .. tostring(emu.getsystemid()),
    "core=" .. tostring(emu.getdisplaytype and emu.getdisplaytype() or "?"),
    "frame=" .. tostring(emu.framecount()),
    "rom=" .. tostring(gameinfo.getromname()),
    "hash=" .. tostring(gameinfo.getromhash()),
  }
  return table.concat(parts, "|")
end

-- READ <hex_addr> <nbytes> [domain]  -> valor sem sinal, little-endian
handlers.READ = function(a)
  local addr = tonumber(a[2], 16) & 0x1FFFFF
  local n = tonumber(a[3]) or 1
  local domain = a[4] or "MainRAM"
  local v
  if n == 1 then v = memory.read_u8(addr, domain)
  elseif n == 2 then v = memory.read_u16_le(addr, domain)
  elseif n == 4 then v = memory.read_u32_le(addr, domain)
  else return "ERR tamanho deve ser 1, 2 ou 4" end
  return tostring(v)
end

-- READRANGE <hex_addr> <len> [domain] -> hex string
handlers.READRANGE = function(a)
  local addr = tonumber(a[2], 16) & 0x1FFFFF
  local len = tonumber(a[3]) or 1
  local domain = a[4] or "MainRAM"
  return hexdump(read_range(addr, len, domain))
end

-- DOMAINS -> lista os dominios de memoria disponiveis no core atual
-- ATENCAO: o BizHawk devolve esse array INDEXADO EM 0. Usar ipairs() aqui
-- silenciosamente pula a primeira entrada - que e justamente a MainRAM.
handlers.DOMAINS = function()
  local list = memory.getmemorydomainlist()
  local t = {}
  local i = 0
  while list[i] ~= nil do
    local d = list[i]
    t[#t + 1] = d .. ":" .. tostring(memory.getmemorydomainsize(d))
    i = i + 1
  end
  -- fallback caso alguma versao devolva indexado em 1
  if #t == 0 then
    for _, d in ipairs(list) do
      t[#t + 1] = d .. ":" .. tostring(memory.getmemorydomainsize(d))
    end
  end
  return table.concat(t, ",")
end

-- PRESS <button> [frames]
handlers.PRESS = function(a)
  return press(a[2], tonumber(a[3]))
end

-- SEQ <btn:frames,btn:frames,...>
handlers.SEQ = function(a)
  for item in string.gmatch(a[2] or "", "[^,]+") do
    local btn, fr = string.match(item, "([^:]+):?(%d*)")
    press(btn, tonumber(fr) or 2)
  end
  return "OK"
end

-- FRAME [n] -> avanca n frames
handlers.FRAME = function(a)
  local n = tonumber(a[2]) or 1
  for _ = 1, n do emu.frameadvance() end
  return tostring(emu.framecount())
end

-- FREERUN <frames> -> roda o jogo em velocidade normal por N frames e devolve
-- os botoes que o HUMANO apertou, com o frame de cada aperto.
--
-- Existe para observar uma pessoa jogando: o laco normal da ponte so avanca um
-- frame por poll do socket, o que deixa o jogo lento demais para alguem jogar.
-- Aqui o Lua fica no controle do avanco e so devolve o log no fim.
handlers.FREERUN = function(a)
  local n = tonumber(a[2]) or 600
  local log = {}
  local anterior = ""
  for _ = 1, n do
    local apertados = {}
    for nome, ligado in pairs(joypad.get(1)) do
      if ligado == true then apertados[#apertados + 1] = tohex(nome) end
    end
    table.sort(apertados)
    local atual = table.concat(apertados, "+")
    if atual ~= anterior and atual ~= "" then
      log[#log + 1] = emu.framecount() .. "=" .. atual
    end
    anterior = atual
    emu.frameadvance()
  end
  return table.concat(log, ",")
end

-- SCREENSHOT <path>
handlers.SCREENSHOT = function(a)
  local path = a[2]
  if not path then return "ERR falta o caminho" end
  client.screenshot(path)
  return "OK " .. path
end

-- SPEED <percent>  (100 = normal; valores altos = fast-forward)
handlers.SPEED = function(a)
  local pct = tonumber(a[2]) or 100
  client.speedmode(pct)
  return "OK " .. tostring(pct)
end

-- SAVESTATE <path> / LOADSTATE <path>
handlers.SAVESTATE = function(a)
  savestate.save(a[2]); return "OK"
end
handlers.LOADSTATE = function(a)
  savestate.load(a[2]); return "OK"
end

-- MMFDUMP <hex_addr> <len> <mmf_name> -> despeja bloco grande via memory-mapped file
handlers.MMFDUMP = function(a)
  local addr = tonumber(a[2], 16) & 0x1FFFFF
  local len = tonumber(a[3])
  local name = a[4] or "exodia_ram"
  local n = comm.mmfCopyFromMemory(name, addr, len, "MainRAM")
  return "OK " .. tostring(n)
end

-- ---------------------------------------------------------------- loop

local function handle(line)
  if not line or line == "" then return nil end
  local a = split(line)
  local h = handlers[string.upper(a[1] or "")]
  if not h then return "ERR comando desconhecido: " .. tostring(a[1]) end
  local ok, res = pcall(h, a)
  if not ok then return "ERR " .. tostring(res) end
  return res
end

console.log("EXODIA bridge.lua carregado. Aguardando o servidor Python...")

local pending = "HELLO"

while true do
  comm.socketServerSend(pending)
  local cmd = comm.socketServerResponse()
  if cmd and cmd ~= "" then
    local res = handle(cmd)
    pending = res or "OK"
  else
    -- nada chegou: adianta um frame para a UI do EmuHawk nao congelar
    pending = "IDLE"
    emu.frameadvance()
  end
end
