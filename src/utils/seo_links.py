import re
from src.utils.logger import setup_logger

logger = setup_logger("seo_links")


def _build_game_pattern(game_name: str) -> re.Pattern:
    tokens = [t for t in re.split(r"[\s\-]+", game_name.strip()) if t]
    if not tokens:
        return re.compile(re.escape(game_name), re.IGNORECASE)
    joined = r"[\s\-]+".join(re.escape(t) for t in tokens)
    return re.compile(rf"\b{joined}\b", re.IGNORECASE)


def _should_link_line(line: str) -> bool:
    if not line.strip():
        return False
    if line.strip().startswith(("|", "-", "*", "<", ">")):
        return False
    if len(line.strip()) < 30:
        return False
    return True


def apply_game_link(final_path: str, game_name: str, game_slug: str) -> None:
    if not final_path or not game_name or not game_slug:
        logger.warning(f"Skip link: path={final_path}, name={game_name}, slug={game_slug}")
        return
    logger.info(f"Applying SEO links for: {game_name} (slug: {game_slug})")
    try:
        with open(final_path, "r", encoding="utf-8") as f:
            content = f.read()

        frontmatter = ""
        body = content
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) == 3:
                frontmatter = "---" + parts[1] + "---"
                body = parts[2]

        pattern = _build_game_pattern(game_name)
        link_prefix = f"/games/{game_slug}"

        lines = body.splitlines()
        updated_lines = []
        links_added = 0

        for line in lines:
            stripped = line.lstrip()

            if stripped.startswith("#"):
                clean_line = re.sub(r'<a\s+href="[^"]*">([^<]+)</a>', r"\1", line, flags=re.IGNORECASE)
                updated_lines.append(clean_line)
                continue

            if link_prefix in line:
                updated_lines.append(line)
                continue

            if not pattern.search(line):
                updated_lines.append(line)
                continue

            if not _should_link_line(line):
                updated_lines.append(line)
                continue

            def _repl(match: re.Match) -> str:
                text = match.group(0)
                return f'<a href="/games/{game_slug}">{text}</a>'

            new_line = pattern.sub(_repl, line)
            if new_line != line:
                links_added += 1
            updated_lines.append(new_line)

        new_body = "\n".join(updated_lines)
        new_body = re.sub(r"^(Hook|Introduction|Conclusion|Key Points|Bottom Line|Final Verdict):\s*", "", new_body, flags=re.MULTILINE)

        new_content = frontmatter + new_body if frontmatter else new_body
        with open(final_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        logger.info(f"SEO links applied: {links_added} links added for {game_name}")
    except Exception as e:
        logger.error(f"Failed to apply SEO link for {game_name}: {e}")
