"""This module provides the implementation for the retrieving completion results
from bash.
"""
# developer note: this file should not perform any action on import.
import os
import re
import sys
import shlex
import pathlib
import platform
import subprocess

__version__ = '0.1.0'


def _git_for_windows_path():
    """Returns the path to git for windows, if available and None otherwise."""
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             'SOFTWARE\\GitForWindows')
        gfwp, _ = winreg.QueryValueEx(key, "InstallPath")
    except FileNotFoundError:
        gfwp = None
    return gfwp


def _windows_bash_command():
    """Determines the command for Bash on windows."""
    # Check that bash is on path otherwise try the default directory
    # used by Git for windows
    wbc = 'bash'
    try:
        subprocess.check_call([wbc, '--version'],
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    except (FileNotFoundError, subprocess.CalledProcessError):
        gfwp = _git_for_windows_path()
        if gfwp:
            bashcmd = os.path.join(gfwp, 'bin\\bash.exe')
            if os.path.isfile(bashcmd):
                wbc = bashcmd
    return wbc


def _bash_command():
    """Determines the command for Bash on the current plaform."""
    if platform.system() == 'Windows':
        bc = _windows_bash_command()
    else:
        bc = 'bash'
    return bc


def _bash_completion_paths_default():
    """A possibly empty tuple with default paths to Bash completions known for
    the current platform.
    """
    platform_sys = platform.system()
    if platform_sys == 'Linux' or sys.platform == 'cygwin':
        bcd = ('/usr/share/bash-completion/bash_completion', )
    elif platform_sys == 'Darwin':
        bcd = ('/usr/local/share/bash-completion/bash_completion',  # v2.x
               '/usr/local/etc/bash_completion')  # v1.x
    elif platform_sys == 'Windows':
        gfwp = _git_for_windows_path()
        if gfwp:
            bcd = (os.path.join(gfwp, 'usr\\share\\bash-completion\\'
                                      'bash_completion'),
                   os.path.join(gfwp, 'mingw64\\share\\git\\completion\\'
                                      'git-completion.bash'))
        else:
            bcd = ()
    else:
        bcd = ()
    return bcd


_BASH_COMPLETIONS_PATHS_DEFAULT = None


def _get_bash_completions_source(paths=None):
    global _BASH_COMPLETIONS_PATHS_DEFAULT
    if paths is None:
        if _BASH_COMPLETIONS_PATHS_DEFAULT is None:
            _BASH_COMPLETIONS_PATHS_DEFAULT = _bash_completion_paths_default()
        paths = _BASH_COMPLETIONS_PATHS_DEFAULT
    for path in map(pathlib.Path, paths):
        if path.is_file():
            return 'source "{}"'.format(path.as_posix())
    return None


def _bash_get_sep():
    """ Returns the appropriate filepath separator char depending on OS and
    xonsh options set
    """
    if platform.system() == 'Windows':
        return os.altsep
    else:
        return os.sep


_BASH_PATTERN_NEED_QUOTES = None


def _bash_pattern_need_quotes():
    global _BASH_PATTERN_NEED_QUOTES
    if _BASH_PATTERN_NEED_QUOTES is not None:
        return _BASH_PATTERN_NEED_QUOTES
    pattern = r'\s`\$\{\}\,\*\(\)"\'\?&'
    if platform.system() == 'Windows':
        pattern += '%'
    pattern = '[' + pattern + ']' + r'|\band\b|\bor\b'
    _BASH_PATTERN_NEED_QUOTES = re.compile(pattern)
    return _BASH_PATTERN_NEED_QUOTES


def _bash_expand_path(s):
    """Takes a string path and expands ~ to home and environment vars."""
    # expand ~ according to Bash unquoted rules "Each variable assignment is
    # checked for unquoted tilde-prefixes immediately following a ':' or the
    # first '='". See the following for more details.
    # https://www.gnu.org/software/bash/manual/html_node/Tilde-Expansion.html
    pre, char, post = s.partition('=')
    if char:
        s = os.path.expanduser(pre) + char
        s += os.pathsep.join(map(os.path.expanduser, post.split(os.pathsep)))
    else:
        s = os.path.expanduser(s)
    return s


def _bash_quote_to_use(x):
    single = "'"
    double = '"'
    if single in x and double not in x:
        return double
    else:
        return single


def _bash_quote_paths(paths, start, end):
    out = set()
    space = ' '
    backslash = '\\'
    double_backslash = '\\\\'
    slash = _bash_get_sep()
    orig_start = start
    orig_end = end
    # quote on all or none, to make readline completes to max prefix
    need_quotes = any(
        re.search(_bash_pattern_need_quotes(), x) or
        (backslash in x and slash != backslash)
        for x in paths)

    for s in paths:
        start = orig_start
        end = orig_end
        if start == '' and need_quotes:
            start = end = _bash_quote_to_use(s)
        if os.path.isdir(_bash_expand_path(s)):
            _tail = slash
        elif end == '':
            _tail = space
        else:
            _tail = ''
        if start != '' and 'r' not in start and backslash in s:
            start = 'r%s' % start
        s = s + _tail
        if end != '':
            if "r" not in start.lower():
                s = s.replace(backslash, double_backslash)
            if s.endswith(backslash) and not s.endswith(double_backslash):
                s += backslash
        if end in s:
            s = s.replace(end, ''.join('\\%s' % i for i in end))
        out.add(start + s + end)
    return out


BASH_COMPLETE_SCRIPT = r"""
{source}

# Override some functions in bash-completion, do not quote for readline
quote_readline()
{{
    echo "$1"
}}

_quote_readline_by_ref()
{{
    if [[ $1 == \'* ]]; then
        # Leave out first character
        printf -v $2 %s "${{1:1}}"
    else
        printf -v $2 %s "$1"
    fi

    [[ ${{!2}} == \$* ]] && eval $2=${{!2}}
}}


function _get_complete_statement {{
    complete -p {cmd} 2> /dev/null || echo "-F _minimal"
}}

_complete_stmt=$(_get_complete_statement)
if echo "$_complete_stmt" | grep --quiet -e "_minimal"
then
    declare -f _completion_loader > /dev/null && _completion_loader {cmd}
    _complete_stmt=$(_get_complete_statement)
fi

_func=$(echo "$_complete_stmt" | grep -o -e '-F \w\+' | cut -d ' ' -f 2)
declare -f "$_func" > /dev/null || exit 1

echo "$_complete_stmt"
COMP_WORDS=({line})
COMP_LINE={comp_line}
COMP_POINT=${{#COMP_LINE}}
COMP_COUNT={end}
COMP_CWORD={n}
$_func {cmd} {prefix} {prev}

for ((i=0;i<${{#COMPREPLY[*]}};i++)) do echo ${{COMPREPLY[i]}}; done
"""


def bash_completions(prefix, line, begidx, endidx, env=None, paths=None,
                     command=None, quote_paths=_bash_quote_paths, **kwargs):
    """Completes based on results from BASH completion.

    Parameters
    ----------
    prefix : str
        The string to match
    line : str
        The line that prefix appears on.
    begidx : int
        The index in line that prefix starts on.
    endidx : int
        The index in line that prefix ends on.
    env : Mapping, optional
        The environment dict to execute the Bash suprocess in.
    paths : list or tuple of str or None, optional
        This is a list (or tuple) of strings that specifies where the
        ``bash_completion`` script may be found. The first valid path will
        be used. For better performance, bash-completion v2.x is recommended
        since it lazy-loads individual completion scripts. For both
        bash-completion v1.x and v2.x, paths of individual completion scripts
        (like ``.../completes/ssh``) do not need to be included here. The
        default values are platform dependent, but sane.
    command : str or None, optional
        The /path/to/bash to use. If None, it will be selected based on the
        from the environment and platform.
    quote_paths : callable, optional
        A functions that quotes file system paths. You shouldn't normally need
        this as the default is acceptable 99+% of the time.

    Returns
    -------
    rtn : list of str
        Possible completions of prefix, sorted alphabetically.
    lprefix : int
        Length of the prefix to be replaced in the completion.
    """
    source = _get_bash_completions_source(paths) or set()

    if prefix.startswith('$'):  # do not complete env variables
        return set(), 0

    splt = line.split()
    cmd = splt[0]
    idx = n = 0
    prev = ''
    for n, tok in enumerate(splt):
        if tok == prefix:
            idx = line.find(prefix, idx)
            if idx >= begidx:
                break
        prev = tok

    if len(prefix) == 0:
        prefix_quoted = '""'
        n += 1
    else:
        prefix_quoted = shlex.quote(prefix)

    script = BASH_COMPLETE_SCRIPT.format(
        source=source, line=' '.join(shlex.quote(p) for p in splt),
        comp_line=shlex.quote(line), n=n, cmd=shlex.quote(cmd),
        end=endidx + 1, prefix=prefix_quoted, prev=shlex.quote(prev),
    )

    if command is None:
        command = _bash_command()
    try:
        out = subprocess.check_output(
            [command, '-c', script], universal_newlines=True,
            stderr=subprocess.PIPE, env=env)
    except (subprocess.CalledProcessError, FileNotFoundError,
            UnicodeDecodeError):
        return set(), 0

    out = out.splitlines()
    complete_stmt = out[0]
    out = set(out[1:])

    # From GNU Bash document: The results of the expansion are prefix-matched
    # against the word being completed

    # Ensure input to `commonprefix` is a list (now required by Python 3.6)
    commprefix = os.path.commonprefix(list(out))
    strip_len = 0
    while strip_len < len(prefix):
        if commprefix.startswith(prefix[strip_len:]):
            break
        strip_len += 1

    if '-o noquote' not in complete_stmt:
        out = quote_paths(out, '', '')
    if '-o nospace' in complete_stmt:
        out = set([x.rstrip() for x in out])

    return out, len(prefix) - strip_len
