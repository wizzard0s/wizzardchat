# User Guide

This guide covers day-to-day use of the WizzardChat interface. All pages are accessible from the left-hand navigation sidebar.

---

## Navigation Overview

| Page | URL | Purpose |
|------|-----|---------|
| Dashboard | `/` | Live session feed — active, waiting, closed interactions |
| Agent Panel | `/agent` | Handle assigned chat sessions |
| Flow Designer | `/flow-designer` | Build and edit automated chat flows |
| Connectors | `/connectors` | Manage chat widget embed points |
| Queues | `/queues` | Define agent routing groups |
| Campaigns | `/campaigns` | Outbound contact campaigns |
| Contacts | `/contacts` | CRM — contacts and lists |
| Teams | `/teams` | Group agents into teams |
| Roles | `/roles` | Define custom permission sets |
| Users | `/users` | User accounts and permissions |
| Outcomes | `/outcomes` | Configurable call/chat disposition codes |
| Tags | `/tags` | Manage tagging taxonomy |
| Office Hours | `/office-hours` | Define operating schedules |
| Settings | `/settings` | Global platform configuration |

---

## Logging In

Navigate to **http://localhost:8092** (or your deployment URL). Enter your username and password.

- Default admin: `admin` / `M@M@5t3r`
- Sessions expire after 8 hours by default (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`)

---

## Dashboard — Session Management

The Dashboard shows all active interactions in real time.

### Session Cards

Each card shows:
- Visitor name/ID and connector channel
- Current status badge: **In Flow**, **Waiting Agent**, **With Agent**, **Closed**
- Queue assignment (if routed)
- Last message preview and timestamp

### Statuses Explained

| Status | Meaning |
|--------|---------|
| **In Flow** | Visitor is being handled by an automated flow |
| **Waiting Agent** | Flow routed to a queue; waiting for a human agent |
| **With Agent** | An agent has taken the session |
| **Closed** | Interaction ended (completed / abandoned / transferred) |

### Taking a Session

Click **Take** on a waiting-agent card to assign it to yourself and open it in the Agent Panel.

---

## Agent Panel

The Agent Panel is your workspace for handling live chat sessions.

### Opening a Session

- Click a session card from the Dashboard, or
- Be auto-assigned when a visitor enters your queue

### Sending Messages

Type in the message box at the bottom and press **Enter** or click **Send**. Supports:
- Plain text
- Emoji (click the 😊 button)
- File attachments (click the 📎 button — images, PDFs, docs up to 10 MB)

### Session History

The full conversation history is shown, including:
- Bot messages from the automated flow phase
- Visitor messages (including emojis and attachments sent before you took the session)
- System events (queue assignment, transfer, end)

### Closing a Session

Click **Close** to end the interaction. You will be prompted to select an **Outcome** (disposition code).

### Transferring a Session

Click **Transfer** to move the session to a different queue.

---

## Flow Designer

The Flow Designer lets you build automated conversation flows using a drag-and-drop canvas.

### Creating a New Flow

1. Go to **Connectors** and click your connector → **Edit Flow**, or
2. Navigate to `/flow-designer` and click **New Flow**

### Canvas Controls

| Action | How |
|--------|-----|
| Pan | Click and drag the canvas background |
| Zoom | Scroll wheel |
| Select a node | Click it |
| Move a node | Drag it |
| Connect nodes | Drag from a node's output port to another node's input port |
| Delete node/edge | Select it, press **Delete** |
| Undo | Ctrl+Z |

### Adding Nodes

Click **+ Add Node** in the toolbar and choose a node type from the panel on the right.

### Node Types

#### Flow Control

| Node | Description |
|------|-------------|
| **Start** | Every flow must have exactly one Start node. It is the entry point. Configure the trigger type (inbound chat, API, scheduled, etc.) |
| **End** | Terminates the interaction. Choose a status (completed / failed / abandoned) and optional closing message |
| **Condition** | Branches the flow. Configure a variable, operator, and value. Outputs to **true** edge or **false** edge |
| **GoTo** | Jumps to a node by label. Useful for loops (e.g. re-asking a question after invalid input) |
| **Sub-Flow** | Runs another flow inline as a reusable module, then returns to the parent flow when the sub-flow's End node is reached |

#### Interaction

| Node | Description |
|------|-------------|
| **Message** | Sends a text message to the visitor. Supports `{{variable}}` template syntax |
| **Input** | Asks the visitor a question and stores their answer in a named variable. Supports validation (any, number, email, phone, date, regex) |
| **DTMF** | Single-key numeric input (e.g. "Press 1 for Sales") |
| **Menu** | Displays a multiple-choice button menu. Each option has a key and label. Connects to branch edges by option key |

#### Routing

| Node | Description |
|------|-------------|
| **Queue** | Routes the visitor to a human agent queue. Displays a holding message. Supports auto-assignment if agents are available |

#### Data

| Node | Description |
|------|-------------|
| **Set Variable** | Sets a flow context variable (e.g. `greeting = "Hi there"`) |

### Using Variables in Messages

Use double curly braces to insert flow context variables into any message or prompt text:

```
Welcome back, {{contact.name}}!
Your reference number is {{flow.ref_number}}.
```

Variables are set by **Input** nodes (stored under the variable name you specify) or **Set Variable** nodes.

### Connecting Nodes

- Drag from the **right handle** (output) of one node to the **left handle** (input) of another.
- **Condition** nodes have two output handles: **true** (green) and **false** (red).
- **Menu** nodes generate one output handle per menu option.

### Saving a Flow

Click **Save** in the toolbar. Flows auto-save node positions when you move nodes.

### Testing a Flow

1. Go to **Connectors** and obtain the **Widget API Key** for your connector.
2. Navigate to `/chat-preview?key=YOUR_API_KEY` to open a live test chat window with the widget embedded.

---

## Connectors

Connectors are the entry points for visitors. Each connector has:
- A unique **API Key** used to identify it
- A linked **Flow** that runs when a visitor connects
- **Allowed Origins** (for CORS control on the embedded widget)
- **Office Hours** schedule
- **Style** config (colours, widget position, greeting message)

### Embedding the Chat Widget

From the **Connectors** page, click **Embed Code** on your connector to get the JavaScript snippet:

```html
<script>
  window.WizzardChat = {
    apiKey: "YOUR_API_KEY",
    serverUrl: "https://your-wizzardchat-domain.com"
  };
</script>
<script src="https://your-wizzardchat-domain.com/static/js/chat-widget.js"></script>
```

Paste this just before the `</body>` tag on your website.

---

## Queues

Queues group agents for routing. When a flow reaches a **Queue** node, the interaction is placed into that queue and agents members see the session appear in their panel.

### Creating a Queue

1. Go to **Queues** → **New Queue**
2. Set a name, colour, and optionally link a campaign for outbound context
3. Add outcome codes that agents must select when closing a session from this queue

### Auto-Assignment

When a session enters a queue, WizzardChat immediately checks for an available online agent in that queue and auto-assigns if found. If no agent is available, the session appears in the **Waiting** list for manual pickup.

---

## Campaigns

Campaigns are used for outbound contact targeting and give agents context when handling sessions from a specific campaign queue.

### Creating a Campaign

1. **Campaigns** → **New Campaign**
2. Set name, linked queues, agents, and optionally campaign schedule times
3. Set allowed outcomes specific to the campaign

---

## Contacts & Lists

The Contacts section is a full CRM. Each contact has:

- Name, email, phone, address
- Title, job title, date of birth, gender, language
- Source (where they came from), notes
- Membership in one or more **Contact Lists**
- **Tags** for flexible categorisation

### Importing Contacts

Use the **Import** button to upload a CSV. Required columns: `name`, `email` or `phone`. All other fields are optional.

### Contact Lists

Lists let you group contacts for campaigns. Create a list under **Contacts → Lists** and assign contacts to it.

---

## Office Hours

Office hours define when a connector is "open". Visitors connecting outside hours receive the configured out-of-hours message and do not enter the flow.

### Configuring a Schedule

1. Go to **Office Hours** → **New Schedule**
2. Set the timezone (default: `Africa/Johannesburg`)
3. Enable days and set open/close times per day
4. Set the out-of-hours message
5. Assign the schedule to a connector from the **Connectors** page

---

## Teams, Roles & Users

### Teams

Teams group agents for reporting and organisational purposes. An agent belongs to at most one team.

### Roles

Roles define what a user can do. The system ships with:

| Role | Access |
|------|--------|
| **Super Admin** | Full access to everything |
| **Admin** | Full access except system settings |
| **Supervisor** | Read access to all sessions + reports |
| **Agent** | Own sessions only |

Custom roles can be created under **Roles** with granular permission toggles per module.

### Users

Manage user accounts under **Users**. Each user has:
- Username, email, full name
- Role assignment
- Queue membership (set via **Queues**)
- Team membership (set via **Teams**)

---

## Outcomes & Tags

### Outcomes

Outcomes are the disposition codes agents select when closing a session. They are linked per-queue and per-campaign so you can have different outcome sets for different contexts.

### Tags

Tags are free-form labels that can be applied to interactions and contacts for filtering and reporting purposes. Create your tag taxonomy under **Tags**.

---

## Settings

Global platform settings are under **Settings**:

| Setting | Description |
|---------|-------------|
| Platform name | Displayed in the browser title and header |
| Default language | Platform UI language |
| Default timezone | Used for timestamps and office hours |
| Chat retention | How long to keep closed interaction records |
| Max file upload size | Maximum attachment size in MB |
| SMTP config | For email notifications (future feature) |
