/** Spanish (default) resources. Keys are English identifiers; values are the UI copy. */
export const es = {
  app: { name: "Conector", skipToContent: "Saltar al contenido" },
  common: {
    loading: "Cargando…",
    retry: "Reintentar",
    empty: "No hay datos todavía.",
    unexpectedError: "Ha ocurrido un error inesperado.",
    networkError: "No se puede contactar con el servidor.",
    backHome: "Volver al inicio",
  },
  login: {
    title: "Iniciar sesión",
    description: "Accede al panel de administración del conector.",
    username: "Usuario",
    password: "Contraseña",
    submit: "Entrar",
    submitting: "Entrando…",
    errors: {
      invalid_credentials: "Usuario o contraseña incorrectos.",
      rate_limited: "Demasiados intentos. Inténtalo de nuevo en {{seconds}} segundos.",
      rate_limited_unknown: "Demasiados intentos. Inténtalo de nuevo más tarde.",
    },
  },
  nav: {
    label: "Navegación principal",
    dashboard: "Panel",
    connections: "Conexiones",
    resources: "Recursos",
    mappings: "Mapeos",
    jobs: "Tareas",
    runs: "Ejecuciones",
    settings: "Ajustes",
  },
  session: {
    logout: "Cerrar sesión",
    signedInAs: "Sesión iniciada como {{username}}",
    readOnly: "Modo solo lectura: tu rol no permite modificar datos.",
    roles: { admin: "Administrador", operator: "Operador" },
  },
  placeholder: { comingSoon: "Esta sección estará disponible próximamente." },
  errors: {
    notFoundTitle: "Página no encontrada",
    boundaryTitle: "Algo ha fallado",
    boundaryBody:
      "La pantalla no se ha podido mostrar. Recarga la página para volver a intentarlo.",
    reload: "Recargar",
  },
};
