# =============================================================================
# formatters.py — Helpers centralizados de formatação e envio de mensagens
# =============================================================================
# Este módulo encapsula TODA a lógica de formatação de texto e comunicação
# com o Telegram. Nenhum handler em bot.py formata texto manualmente —
# todos delegam para funções aqui.
#
# ARQUITETURA:
#   Seção 1 — Importações e constantes
#   Seção 2 — Helpers de URL (funções puras)
#   Seção 3 — Helpers de formatação (funções puras — sem I/O)
#   Seção 4 — Helpers de envio (async — fazem I/O com Telegram)
#
# DEPENDÊNCIA CHAVE:
#   telegramify-markdown v1.1.1 — converte Markdown padrão (GitHub-flavored)
#   em (texto_limpo, list[MessageEntity]). Isso elimina completamente o
#   problema de parse_mode="Markdown" quebrando com caracteres especiais.
# =============================================================================

import logging

from telegramify_markdown import convert, split_entities


# =============================================================================
# SEÇÃO 1 — CONSTANTES
# =============================================================================

logger = logging.getLogger(__name__)

# Limite de caption para reply_photo() do Telegram (em caracteres texto limpo).
# O limite oficial é 1024 UTF-16 code units, mas captions raramente usam
# emojis pesados, então len() de Python é uma aproximação segura aqui.
TELEGRAM_CAPTION_LIMIT = 1024

# Limite de mensagem de texto do Telegram em UTF-16 code units.
TELEGRAM_MESSAGE_LIMIT = 4096

# Máximo de interessados exibidos na lista monospace do /game.
# Acima disso, exibe "... e mais N pessoas".
MAX_DISPLAYED_USERS = 6

# Mapeamento de emoji de status → (linha bold, tagline itálica)
# Usado por build_status_blockquote() para gerar o card visual.
STATUS_BLOCKQUOTES: dict[str, tuple[str, str]] = {
    "🔥": ("🔥 **MENOR PREÇO HISTÓRICO!**", "Nunca esteve tão barato."),
    "✅": ("✅ **Bom preço — 30%+ de desconto**", "Vale considerar rachar agora."),
    "❌": ("❌ **Aguardar promoção**", "Preço atual não justifica o racha."),
    "❓": ("❓ **Dados insuficientes**", "Use /update para buscar preços."),
}


# =============================================================================
# SEÇÃO 2 — HELPERS DE URL
# =============================================================================

def steam_store_url(app_id: str) -> str:
    """Retorna a URL da página do jogo na Steam Store.

    Args:
        app_id: O AppID numérico do jogo na Steam.

    Returns:
        URL completa da página do jogo. Ex: "https://store.steampowered.com/app/1091500/"
    """
    return f"https://store.steampowered.com/app/{app_id}/"


def steam_banner_url(app_id: str) -> str:
    """Retorna a URL do banner (header.jpg) do jogo no CDN da Steam.

    O banner tem 460×215px — tamanho ideal para mobile, carrega rápido.
    Disponível publicamente sem autenticação para qualquer jogo publicado.

    Args:
        app_id: O AppID numérico do jogo na Steam.

    Returns:
        URL do banner. Ex: "https://cdn.akamai.steamstatic.com/steam/apps/1091500/header.jpg"
    """
    return f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg"


# =============================================================================
# SEÇÃO 3 — HELPERS DE FORMATAÇÃO (funções puras — sem I/O)
# =============================================================================

def _format_price(price: float, fallback: str = "N/D") -> str:
    """Formata um preço float como string BRL, com fallback para sentinela.

    Sentinel value -1.0 (ou qualquer negativo) indica dados indisponíveis.
    Preço 0.0 indica jogo gratuito.

    Args:
        price: O preço em BRL. Negativo = dados indisponíveis.
        fallback: Texto a exibir quando o preço é indisponível.

    Returns:
        String formatada: "R$ 59,90", "Grátis 🎉", ou o fallback.
    """
    if price < 0:
        return fallback
    if price == 0.0:
        return "Grátis 🎉"
    return f"R$ {price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _get_status_emoji(current_price: float, best_deal: float, historical_low: float) -> str:
    """Determina o emoji de status de deal baseado nos dados de preço.

    Regras (em ordem de prioridade):
      🔥 — Deal atual ≤ mínimo histórico (± R$0.01). Melhor momento para comprar.
      ✅ — Deal atual ≥ 30% de desconto sobre o preço Steam. Bom negócio.
      ❌ — Nenhuma condição acima. Melhor aguardar.
      ❓ — Sem dados de preço suficientes.

    Args:
        current_price: Preço oficial na Steam em BRL.
        best_deal: Melhor oferta atual em todas as lojas (ITAD).
        historical_low: Menor preço já registrado (ITAD).
    """
    # Sem dados utilizáveis
    if current_price < 0 and best_deal < 0:
        return "❓"

    # O preço de referência é o melhor deal se disponível, senão o preço Steam
    reference_price = best_deal if best_deal >= 0 else current_price

    # 🔥 No mínimo histórico (ou dentro de R$0.01)
    if historical_low >= 0 and reference_price <= historical_low + 0.01:
        return "🔥"

    # ✅ Pelo menos 30% de desconto em relação ao preço Steam
    if current_price > 0 and best_deal >= 0:
        discount_pct = (current_price - best_deal) / current_price * 100
        if discount_pct >= 30:
            return "✅"

    # ❌ Sem promoção relevante
    return "❌"


def format_per_person(game: dict) -> str:
    """Calcula e formata o preço por pessoa para um jogo.

    Usa o melhor deal disponível (ITAD) se existir, senão o preço Steam.
    Se o preço é 0.0 (grátis) ou não há interessados, retorna "—".

    Args:
        game: Dicionário do jogo com campos current_price, best_deal_price, interested_users.

    Returns:
        "R$ 25,50" ou "—" se não calculável.
    """
    interested = game.get("interested_users", [])
    total = len(interested)
    if total == 0:
        return "—"

    current_price = game.get("current_price", -1.0)
    best_deal = game.get("best_deal_price", -1.0)

    # Usa o melhor deal se disponível, senão o preço Steam
    split_price = best_deal if best_deal >= 0 else current_price

    # Sem preço ou jogo grátis → não faz sentido dividir
    if split_price <= 0:
        return "—"

    per_person = split_price / total
    return f"R$ {per_person:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def build_status_blockquote(emoji: str) -> str:
    """Gera o bloco de status formatado como blockquote Markdown.

    Args:
        emoji: O emoji de status ("🔥", "✅", "❌", "❓").

    Returns:
        String com blockquote. Ex:
        "> 🔥 **MENOR PREÇO HISTÓRICO!**
        "> *Nunca esteve tão barato.*"
    """
    bold_line, italic_line = STATUS_BLOCKQUOTES.get(
        emoji, ("❓ **Status desconhecido**", "")
    )
    if italic_line:
        return f"> {bold_line}\n> *{italic_line}*"
    return f"> {bold_line}"


def build_interests_inline(game: dict) -> tuple[str, str]:
    """Formata a lista de interessados inline (para /list — compacta).

    Args:
        game: Dicionário do jogo com campo interested_users.

    Returns:
        Tupla (people_str, per_person_str).
        people_str: "(3) @lucas, @joao, @ana" ou "Ninguém ainda".
        per_person_str: "R$ 25,50" ou "—".
    """
    interested = game.get("interested_users", [])
    total = len(interested)

    if total == 0:
        return "Ninguém ainda", "—"

    names = []
    for u in interested:
        uname = u.get("username", "?")
        names.append(f"@{uname}" if " " not in uname else uname)
    people_str = f"({total}) {', '.join(names)}"

    per_person_str = format_per_person(game)
    return people_str, per_person_str


def build_interests_block(game: dict, app_id: str) -> str:
    """Formata a lista de interessados como bloco monospace numerado (para /game).

    Exibe no máximo MAX_DISPLAYED_USERS (6). Se exceder, indica quantos mais.
    Dentro do bloco monospace, nenhum escape é necessário (caracteres como _
    são literais em blocos de código).

    Args:
        game: Dicionário do jogo.
        app_id: AppID do jogo (para mensagem de "ninguém ainda").

    Returns:
        String com bloco monospace numerado, ou mensagem convidando /want.
    """
    interested = game.get("interested_users", [])
    total = len(interested)

    if total == 0:
        return f"*Ninguém ainda — use* `/want {app_id}` *para entrar!*"

    # Limitar exibição a MAX_DISPLAYED_USERS
    displayed = interested[:MAX_DISPLAYED_USERS]
    lines = []
    for i, u in enumerate(displayed, start=1):
        uname = u.get("username", "?")
        display = f"@{uname}" if " " not in uname else uname
        lines.append(f"{i}. {display}")

    block = "```\n" + "\n".join(lines)

    # Se há mais do que o limite, adicionar "... e mais N"
    remaining = total - MAX_DISPLAYED_USERS
    if remaining > 0:
        block += f"\n... e mais {remaining} pessoa{'s' if remaining > 1 else ''}"

    block += "\n```"
    return block


def build_list_block(app_id: str, game: dict) -> str:
    """Monta um bloco de texto Markdown para um jogo no /list.

    Cada bloco inclui: status emoji, nome linkado, preço Steam, melhor deal,
    mínimo histórico, interessados inline e preço por pessoa.

    Args:
        app_id: AppID do jogo.
        game: Dicionário completo do jogo.

    Returns:
        String Markdown com as informações do jogo formatadas.
    """
    name = game.get("name", "Jogo Desconhecido")
    current_price = game.get("current_price", -1.0)
    best_deal = game.get("best_deal_price", -1.0)
    deal_shop = game.get("best_deal_shop", "")
    hist_low = game.get("historical_low", -1.0)

    # Status emoji
    status = _get_status_emoji(current_price, best_deal, hist_low)

    # Preços formatados
    steam_str = _format_price(current_price)

    deal_str = _format_price(best_deal)
    if deal_shop and best_deal >= 0:
        deal_str += f" ({deal_shop})"

    low_str = _format_price(hist_low)

    # Interessados
    people_str, per_person_str = build_interests_inline(game)

    # Nome linkado para a Steam Store
    store_url = steam_store_url(app_id)

    block = (
        f"{status} [{name}]({store_url}) — `{app_id}`\n"
        f"  🏪 Steam: {steam_str}  |  🔥 Melhor Deal: {deal_str}  |  📉 Mín.: {low_str}\n"
        f"  👥 {people_str}\n"
        f"  💸 Por pessoa: {per_person_str}"
    )
    return block


def build_game_summary_caption(game: dict, app_id: str) -> str:
    """Monta o caption da foto do /game (bloco resumo com preços e status).

    Este texto é enviado como caption de reply_photo(), com limite de 1024 chars.
    Contém: nome linkado, AppID, preços e blockquote de status.
    NÃO inclui a lista de interessados (vai no segundo envio separado).

    Args:
        game: Dicionário completo do jogo.
        app_id: AppID do jogo.

    Returns:
        String Markdown com o resumo do jogo para caption.
    """
    name = game.get("name", "Jogo Desconhecido")
    current_price = game.get("current_price", -1.0)
    best_deal = game.get("best_deal_price", -1.0)
    deal_shop = game.get("best_deal_shop", "")
    hist_low = game.get("historical_low", -1.0)

    # Status
    status = _get_status_emoji(current_price, best_deal, hist_low)

    # Preços
    steam_str = _format_price(current_price)

    deal_str = _format_price(best_deal)
    if deal_shop and best_deal >= 0:
        deal_str += f" (*via {deal_shop}*)"

    low_str = _format_price(hist_low)

    # Nome linkado
    store_url = steam_store_url(app_id)

    # Blockquote de status
    status_block = build_status_blockquote(status)

    caption = (
        f"🎮 [{name}]({store_url})\n"
        f"📋 AppID: `{app_id}`\n\n"
        f"**💰 Preços (BRL):**\n"
        f"  🏪 Steam: {steam_str}\n"
        f"  🔥 Melhor deal: {deal_str}\n"
        f"  📉 Mínimo histórico: {low_str}\n\n"
        f"{status_block}"
    )
    return caption


def build_game_interests_text(game: dict, app_id: str) -> str:
    """Monta o segundo bloco de texto do /game (interessados + preço por pessoa).

    Este texto é enviado como reply_text separado após o banner.
    Inclui a lista monospace e o preço por pessoa com spoiler.

    Args:
        game: Dicionário completo do jogo.
        app_id: AppID do jogo.

    Returns:
        String Markdown com o bloco de interessados e preço por pessoa.
    """
    interested = game.get("interested_users", [])
    total = len(interested)

    interests_block = build_interests_block(game, app_id)
    per_person = format_per_person(game)

    # Spoiler no preço por pessoa (Feature 3)
    if per_person != "—":
        per_person_display = f"||{per_person}|| *(toque para revelar)*"
    else:
        per_person_display = "—"

    text = (
        f"**👥 Interessados ({total}):**\n"
        f"{interests_block}\n\n"
        f"**💸 Preço por pessoa:** {per_person_display}"
    )
    return text


# =============================================================================
# SEÇÃO 4 — HELPERS DE ENVIO (async — fazem I/O com Telegram)
# =============================================================================

async def send_md(message, markdown_text: str) -> None:
    """Converte Markdown padrão para entities e envia como reply.

    Processo:
      1. convert(markdown) → (texto_limpo, list[MessageEntity])
      2. reply_text(texto_limpo, entities=[...])

    Nenhum parse_mode é passado — o Telegram aplica as entities diretamente.
    Se convert() falhar por qualquer motivo, faz fallback para texto puro.

    Args:
        message: Objeto Message do python-telegram-bot (tem .reply_text()).
        markdown_text: String em Markdown padrão (GitHub-flavored).
    """
    try:
        text, entities = convert(markdown_text)
        await message.reply_text(
            text,
            entities=[e.to_dict() for e in entities]
        )
    except Exception:
        logger.warning(
            "[formatters] convert() falhou, enviando como texto puro",
            exc_info=True
        )
        await message.reply_text(markdown_text)


async def edit_md(message, markdown_text: str) -> None:
    """Converte Markdown e edita uma mensagem existente.

    Mesmo padrão de send_md(), mas usa edit_text() em vez de reply_text().
    Usado para editar mensagens de "loading..." do /add e /want.

    Args:
        message: Objeto Message já enviado (tem .edit_text()).
        markdown_text: String em Markdown padrão.
    """
    try:
        text, entities = convert(markdown_text)
        await message.edit_text(
            text,
            entities=[e.to_dict() for e in entities]
        )
    except Exception:
        logger.warning(
            "[formatters] convert() falhou no edit, enviando como texto puro",
            exc_info=True
        )
        await message.edit_text(markdown_text)


async def send_photo_md(message, photo_url: str, caption: str) -> None:
    """Envia uma foto com caption formatado via Markdown → entities.

    Tenta enviar a foto via reply_photo(). Se falhar (banner indisponível,
    timeout, etc.), faz fallback gracioso para send_md() com o caption.

    Args:
        message: Objeto Message do python-telegram-bot.
        photo_url: URL da imagem (ex: Steam CDN header.jpg).
        caption: String em Markdown padrão para caption da foto.
    """
    try:
        cap_text, cap_entities = convert(caption)
        await message.reply_photo(
            photo=photo_url,
            caption=cap_text,
            caption_entities=[e.to_dict() for e in cap_entities]
        )
    except Exception:
        logger.warning(
            "[formatters] reply_photo() falhou para URL: %s — fallback para texto",
            photo_url,
            exc_info=True,
        )
        # Fallback: envia como texto, sem imagem
        await send_md(message, caption)
