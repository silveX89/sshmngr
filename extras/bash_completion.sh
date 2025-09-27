# Bash completion for sshmngr
_sshmngr_complete()
{
    local cur prev words cword
    _init_completion -n : || return

    local cfg="${HOME}/.config/sshmngr/connections.csv"
    if [[ -f "$cfg" ]]; then
        COMPREPLY=( $( compgen -W "$(cut -d',' -f2 "$cfg" | tr -d '\r' )" -- "$cur" ) )
    else
        COMPREPLY=()
    fi
    return 0
}
complete -F _sshmngr_complete sshmngr
