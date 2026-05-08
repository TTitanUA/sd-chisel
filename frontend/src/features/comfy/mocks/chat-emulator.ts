/**
 * Chat emulator. Echoes the user's last message back. Layout-only:
 * we don't care what the chat says in ComfyMock, just how it's laid
 * out and how send/receive interact with the rest of the page. See
 * docs/comfy-agents-ui-mock-plan.md.
 */
export const CHAT_EMULATOR_DELAY_MS = 600;

export async function emulateChatReply(userMessage: string): Promise<string> {
  await new Promise((resolve) => setTimeout(resolve, CHAT_EMULATOR_DELAY_MS));
  return `You said: ${userMessage}`;
}
