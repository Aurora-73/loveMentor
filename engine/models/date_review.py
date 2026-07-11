"""约会复盘模型。"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DateReview:
    date: str = ""
    location: str = ""
    duration_hours: float = 0.0
    cost: float = 0.0
    activities: list[str] = field(default_factory=list)
    initiator: str = "me"
    her_mood: str = ""
    physical_contact: bool = False
    her_response: str = ""
    her_engagement_level: str = "medium"
    comfort_level: str = "medium"
    clear_positive_feedback: bool = False
    my_performance_score: int = 3
    topic_distribution: dict = field(default_factory=dict)
    what_went_well: list[str] = field(default_factory=list)
    what_could_improve: list[str] = field(default_factory=list)
    next_step: str = ""
    next_date_urgency: str = "medium"
    rating: int = 3

    def to_yaml(self) -> dict:
        return {
            "date": self.date,
            "location": self.location,
            "duration_hours": self.duration_hours,
            "cost": self.cost,
            "activities": self.activities,
            "initiator": self.initiator,
            "her_mood": self.her_mood,
            "physical_contact": self.physical_contact,
            "her_response": self.her_response,
            "her_engagement_level": self.her_engagement_level,
            "comfort_level": self.comfort_level,
            "clear_positive_feedback": self.clear_positive_feedback,
            "my_performance_score": self.my_performance_score,
            "topic_distribution": self.topic_distribution,
            "what_went_well": self.what_went_well,
            "what_could_improve": self.what_could_improve,
            "next_step": self.next_step,
            "next_date_urgency": self.next_date_urgency,
            "rating": self.rating,
        }

    @classmethod
    def from_yaml(cls, d: dict) -> "DateReview":
        return cls(**{k: d.get(k, v) for k, v in cls.__dataclass_fields__.items() if k in d or True})
