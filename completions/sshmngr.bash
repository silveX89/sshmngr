# Bash completion for sshmngr
_sshmngr()
{
    local cur prev words cword
    _init_completion -n : || return
    if [[ "$cur" == -* ]]; then
        COMPREPLY=( $(compgen -W "--list-hosts" -- "$cur") )
        return 0
    fi
    local _hosts
    _hosts="$(sshmngr --list-hosts 2>/dev/null)"
    COMPREPLY=( $(compgen -W "${_hosts}" -- "$cur") )
    return 0
}
complete -F _sshmngr sshmngr
complete -F _sshmngr sshmnr
