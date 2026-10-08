import { Component, type ReactNode } from 'react';

type Props = { fallback: (reset: () => void) => ReactNode; children: ReactNode };
type State = { failed: boolean };

/** Contiene el fallo de un fragmento (p. ej. un registro guardado malformado) sin tumbar todo el panel. */
export class ErrorBoundary extends Component<Props, State> {
  override state: State = { failed: false };

  static getDerivedStateFromError(): State { return { failed: true }; }

  reset = () => this.setState({ failed: false });

  override render() { return this.state.failed ? this.props.fallback(this.reset) : this.props.children; }
}
