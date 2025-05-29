# Discord Bot Intents and Permissions Configuration

This document outlines the necessary Discord Gateway Intents, Bot Permissions, and OAuth2 Scopes required for the bot to function correctly.

## Discord Gateway Intents

These must be enabled both in your **Discord Developer Portal** (under your Application > Bot > Privileged Gateway Intents) AND specified in your bot's code when instantiating the `discord.Intents` object.

* **`guilds`**:
    * Usually enabled by `Intents.default()`.
    * Required for basic guild information, server-related events (roles, channels).
* **`members`**:
    * **Privileged Intent - MUST be enabled in Developer Portal.**
    * Required for `on_member_join`, `on_member_remove`, `on_member_update` events, and reliably accessing member information.
* **`message_content`**:
    * **Privileged Intent - MUST be enabled in Developer Portal.**
    * Required to read the content of messages, especially in DMs for the verification process.

## Discord Bot Permissions

These permissions are granted to your bot's role when it's invited to a server or by editing its role in `Server Settings > Roles`.

* **`View Channels`**: Allows the bot to see channels it needs to interact with (e.g., welcome channel, admin notification channel).
* **`Send Messages`**: Allows the bot to send DMs, messages in designated channels (welcome, notifications).
* **`Manage Roles`**: **CRITICAL.** Allows the bot to add and remove roles (verified, unverified, skill roles, etc.).
    * *Note: Ensure the bot's role is higher in the server's role hierarchy than the roles it needs to manage.*
* **`Use Application Commands`**: Essential for users and admins to see and use the bot's slash commands.
* **`Read Message History`**: Primarily for DMs and ensuring context where the bot operates.
* **`Embed Links`**: Recommended, as it allows URLs sent by the bot (e.g., in LLM-generated messages or notifications) to display as rich embeds.

## OAuth2 Scopes (For Bot Invite Link)

When generating the invite link for your bot using the **OAuth2 URL Generator** in the Discord Developer Portal:

1.  **`bot` scope**:
    * This is the primary scope that actually adds your bot user to a server.
2.  **`applications.commands` scope**:
    * This scope is crucial for allowing your bot to create, update, and register its slash commands with the servers it joins. If you only select the `bot` scope, slash commands might not register or update correctly.
