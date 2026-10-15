import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import OtpCodeInput from './otp-code-input';

function Harness() {
  const [value, setValue] = useState('');
  return (
    <>
      <OtpCodeInput value={value} onChange={setValue} />
      <output aria-label="Entered code">{value}</output>
    </>
  );
}

describe('OtpCodeInput', () => {
  it('advances focus as digits are typed', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const first = screen.getByLabelText('Digit 1 of 6');
    const second = screen.getByLabelText('Digit 2 of 6');
    await user.type(first, '1');
    expect(second).toHaveFocus();
    await user.type(second, '2');
    expect(screen.getByLabelText('Entered code')).toHaveTextContent('12');
  });

  it('fills every box from a pasted code', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByLabelText('Digit 1 of 6'));
    await user.paste('12 34-56');
    expect(screen.getByLabelText('Entered code')).toHaveTextContent('123456');
    expect(screen.getByLabelText('Digit 6 of 6')).toHaveValue('6');
  });

  it('backspaces into the previous box', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByLabelText('Digit 1 of 6'));
    await user.paste('12');
    const second = screen.getByLabelText('Digit 2 of 6');
    second.focus();
    await user.keyboard('{Backspace}');
    expect(screen.getByLabelText('Entered code')).toHaveTextContent('1');
    expect(second).toHaveFocus();
    await user.keyboard('{Backspace}');
    expect(screen.getByLabelText('Digit 1 of 6')).toHaveFocus();
  });
});
