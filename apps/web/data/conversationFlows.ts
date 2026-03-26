export interface Message {
  id: string;
  sender: "clinic" | "patient";
  text: string;
  timestamp: string;
  delay?: number; // ms before this message appears
}

export interface ConversationStep {
  messages: Message[];
  patientChoices?: string[];
  nextStepMap?: Record<string, string>; // choice -> stepId
  nextStep?: string; // auto-advance
  isEnd?: boolean;
}

export const conversationSteps: Record<string, ConversationStep> = {
  start: {
    messages: [
      {
        id: "1",
        sender: "clinic",
        text: "So sorry we missed your call. This is Maya from Bright Smile Dental.\n\nAre you a new patient or an existing patient?\n\n1 - New patient\n2 - Existing patient",
        timestamp: "2:34 PM",
        delay: 800,
      },
    ],
    patientChoices: ["1", "2"],
    nextStepMap: {
      "1": "new_patient",
      "2": "existing_patient",
    },
  },

  new_patient: {
    messages: [
      {
        id: "np1",
        sender: "clinic",
        text: "Great, I can get you set up right now! What's your full name?",
        timestamp: "",
        delay: 1000,
      },
    ],
    patientChoices: ["Alice Thompson"],
    nextStepMap: {
      "Alice Thompson": "new_patient_phone",
    },
  },

  new_patient_phone: {
    messages: [
      {
        id: "np2",
        sender: "clinic",
        text: "Nice to meet you, Alice! What's a good number to reach you at?",
        timestamp: "",
        delay: 1200,
      },
    ],
    patientChoices: ["416-555-0201"],
    nextStepMap: {
      "416-555-0201": "new_patient_dob",
    },
  },

  new_patient_dob: {
    messages: [
      {
        id: "np3",
        sender: "clinic",
        text: "And your date of birth? (e.g. March 14, 1985)",
        timestamp: "",
        delay: 1000,
      },
    ],
    patientChoices: ["March 14, 1985"],
    nextStepMap: {
      "March 14, 1985": "new_patient_insurance",
    },
  },

  new_patient_insurance: {
    messages: [
      {
        id: "np4",
        sender: "clinic",
        text: "Do you have dental insurance? If so, which provider? No worries if you don't — just say 'no insurance'!",
        timestamp: "",
        delay: 1200,
      },
    ],
    patientChoices: ["Sun Life", "No insurance"],
    nextStepMap: {
      "Sun Life": "new_patient_appt_type",
      "No insurance": "new_patient_appt_type",
    },
  },

  new_patient_appt_type: {
    messages: [
      {
        id: "np5",
        sender: "clinic",
        text: "What kind of appointment are you looking for?\n\n1 - Cleaning\n2 - General check-up\n3 - New patient exam\n4 - Something urgent",
        timestamp: "",
        delay: 1200,
      },
    ],
    patientChoices: ["1", "2", "3", "4"],
    nextStepMap: {
      "1": "new_patient_date",
      "2": "new_patient_date",
      "3": "new_patient_date",
      "4": "urgent_triage",
    },
  },

  new_patient_date: {
    messages: [
      {
        id: "np6",
        sender: "clinic",
        text: "When works best for you? (like 'next week', 'April 5', etc.)",
        timestamp: "",
        delay: 1000,
      },
    ],
    patientChoices: ["Next week"],
    nextStepMap: {
      "Next week": "schedule_availability",
    },
  },

  existing_patient: {
    messages: [
      {
        id: "ep1",
        sender: "clinic",
        text: "Sure! To find your file, what's your full name and phone number?",
        timestamp: "",
        delay: 1000,
      },
    ],
    patientChoices: ["Alice Thompson, 416-555-0201"],
    nextStepMap: {
      "Alice Thompson, 416-555-0201": "existing_intent",
    },
  },

  existing_intent: {
    messages: [
      {
        id: "ei1",
        sender: "clinic",
        text: "Got it, welcome back Alice! How can I help?\n\n1 - Book an appointment\n2 - Reschedule an appointment\n3 - Cancel an appointment",
        timestamp: "",
        delay: 1500,
      },
    ],
    patientChoices: ["1", "2", "3"],
    nextStepMap: {
      "1": "schedule_availability",
      "2": "reschedule_list",
      "3": "cancel_list",
    },
  },

  reschedule_list: {
    messages: [
      {
        id: "rl1",
        sender: "clinic",
        text: "Here are your upcoming appointments:\n\n1 - Teeth Cleaning — Mon Apr 14, 10:00 AM\n2 - Check-up — Wed Apr 23, 2:30 PM\n\nWhich one would you like to reschedule?",
        timestamp: "",
        delay: 1500,
      },
    ],
    patientChoices: ["1", "2"],
    nextStepMap: {
      "1": "reschedule_date",
      "2": "reschedule_date",
    },
  },

  reschedule_date: {
    messages: [
      {
        id: "rd1",
        sender: "clinic",
        text: "Got it — I'll move your Teeth Cleaning. What dates work better for you?",
        timestamp: "",
        delay: 1000,
      },
    ],
    patientChoices: ["Next Thursday"],
    nextStepMap: {
      "Next Thursday": "schedule_availability",
    },
  },

  cancel_list: {
    messages: [
      {
        id: "cl1",
        sender: "clinic",
        text: "Here are your upcoming appointments:\n\n1 - Teeth Cleaning — Mon Apr 14, 10:00 AM\n2 - Check-up — Wed Apr 23, 2:30 PM\n\nWhich one would you like to cancel?",
        timestamp: "",
        delay: 1500,
      },
    ],
    patientChoices: ["1", "2"],
    nextStepMap: {
      "1": "cancel_reason",
      "2": "cancel_reason",
    },
  },

  cancel_reason: {
    messages: [
      {
        id: "cr1",
        sender: "clinic",
        text: "Got it — I'll cancel your Teeth Cleaning on Apr 14. Mind sharing the reason? (totally fine if it's just scheduling)",
        timestamp: "",
        delay: 1000,
      },
    ],
    patientChoices: ["Scheduling conflict"],
    nextStepMap: {
      "Scheduling conflict": "cancel_confirmed",
    },
  },

  cancel_confirmed: {
    messages: [
      {
        id: "cc1",
        sender: "clinic",
        text: "Done — your Teeth Cleaning on Mon Apr 14 at 10:00 AM has been cancelled. If you ever want to rebook, just text us anytime. - Maya",
        timestamp: "",
        delay: 1200,
      },
    ],
    isEnd: true,
  },

  urgent_triage: {
    messages: [
      {
        id: "u1",
        sender: "clinic",
        text: "Oh no, so sorry to hear that! Can you quickly describe what's going on?\n\nWhere's the pain, how bad on a scale of 1–10, and when did it start?",
        timestamp: "",
        delay: 1000,
      },
    ],
    patientChoices: ["Severe toothache, pain is 8/10, started yesterday"],
    nextStepMap: {
      "Severe toothache, pain is 8/10, started yesterday": "urgent_triage_2",
    },
  },

  urgent_triage_2: {
    messages: [
      {
        id: "u2",
        sender: "clinic",
        text: "I've just sent an alert to our team with your details. Here are our earliest emergency openings:\n\n1 - Today at 4:15 PM\n2 - Tomorrow at 9:00 AM\n3 - Tomorrow at 11:30 AM\n\nWhich works best?",
        timestamp: "",
        delay: 1500,
      },
    ],
    patientChoices: ["1", "2", "3"],
    nextStepMap: {
      "1": "confirm_urgent",
      "2": "confirm_urgent",
      "3": "confirm_urgent",
    },
  },

  confirm_urgent: {
    messages: [
      {
        id: "cu1",
        sender: "clinic",
        text: "You're all set! Here are the details:\n\n📅 Today at 4:15 PM\n📍 Bright Smile Dental — 123 King St W\n🦷 Dr. Patel — Urgent / Pain visit\n\nPlease arrive 10 minutes early. If the pain becomes severe or you experience swelling or difficulty breathing, please call 911.\n\nReply CONFIRM to confirm.",
        timestamp: "",
        delay: 2000,
      },
    ],
    patientChoices: ["CONFIRM"],
    nextStepMap: {
      CONFIRM: "confirmed",
    },
  },

  schedule_availability: {
    messages: [
      {
        id: "sa1",
        sender: "clinic",
        text: "Here are the next available slots for your Teeth Cleaning:\n\n1 - Thursday, Apr 3, 10:00 AM – 11:00 AM\n2 - Friday, Apr 4, 11:00 AM – 12:00 PM\n3 - Saturday, Apr 5, 10:00 AM – 11:00 AM\n\nWhich one works best? Reply with 1, 2, or 3.",
        timestamp: "",
        delay: 1500,
      },
    ],
    patientChoices: ["1", "2", "3"],
    nextStepMap: {
      "1": "confirm_appointment",
      "2": "confirm_appointment",
      "3": "confirm_appointment",
    },
  },

  confirm_appointment: {
    messages: [
      {
        id: "ca1",
        sender: "clinic",
        text: "You're all set! Your Teeth Cleaning is confirmed:\n\nDate: Thursday, April 3\nTime: 10:00 AM – 11:00 AM with Dr. Smith\nLocation: Bright Smile Dental, 123 King St W\n\nWe'll see you then! Reply anytime if you need to make changes. - Maya",
        timestamp: "",
        delay: 1800,
      },
    ],
    isEnd: true,
  },

  confirmed: {
    messages: [
      {
        id: "cf1",
        sender: "clinic",
        text: "Confirmed! ✓ We'll send you a reminder the day before. If you need to reschedule, just text us anytime.\n\nHave a great day! 😊 - Maya",
        timestamp: "",
        delay: 1000,
      },
    ],
    isEnd: true,
  },
};
