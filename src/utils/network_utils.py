"""Windows firewall helper. Adds an inbound rule once so seeding works,
without nagging the user with a UAC prompt on every launch."""
import logging
import platform
import subprocess

logger = logging.getLogger('network')


def _rule_exists(app_name: str) -> bool:
    if platform.system() != 'Windows':
        return False
    try:
        result = subprocess.run(
            ['netsh', 'advfirewall', 'firewall', 'show', 'rule',
             f'name={app_name}'],
            capture_output=True, text=True, timeout=10)
        return result.returncode == 0 and 'No rules match' not in result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def ensure_firewall_rule(app_path: str, config, app_name: str = "BruvTorrent") -> None:
    """Create an inbound allow rule once. The result is cached in config so we
    don't re-prompt. Silently no-ops on non-Windows platforms."""
    if platform.system() != 'Windows':
        return
    if config.get('firewall_rule_created') and _rule_exists(app_name):
        return
    if _rule_exists(app_name):
        config.set('firewall_rule_created', True)
        return

    import ctypes
    command = (
        f'advfirewall firewall add rule name="{app_name}" '
        f'dir=in action=allow program="{app_path}" enable=yes profile=any'
    )
    try:
        # ShellExecuteW with "runas" triggers a single UAC elevation prompt.
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "netsh", command, None, 0)
        if rc > 32:
            config.set('firewall_rule_created', True)
        else:
            logger.info("firewall rule not created (user declined elevation)")
    except OSError as exc:
        logger.warning("could not create firewall rule: %s", exc)
